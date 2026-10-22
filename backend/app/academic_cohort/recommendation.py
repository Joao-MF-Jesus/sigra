"""Read-only v6 candidate adapter and live execution of the existing v4 method.

Frozen scores/TCOs are never inputs. Persisted evaluations authorize documentary
coverage only. User inputs recalculate costs, absolute utilities and contributions.
No operational Vehicle (with invented legacy quality scores) is constructed.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.academic_cohort.contracts import PROFILE_COUNTS, json_document
from app.academic_cohort.repository import AcademicFilters
from app.academic_cohort.service import AcademicUnavailable
from app.academic_cohort.personalization import personalized_fuel, apply_fuel_to_evaluation, personalize_groups
from app.academic_cohort.evidence_diagnostics import documentary_evidence, personalization_evidence
from app.academic_cohort.legacy_calculations import calculate_legacy_subcriteria
from app.academic_cohort import derived_personalization as alternative
from app.academic_cohort import derived_configurations
from data_platform.catalog.academic_cost_scenario import configuration as cost_configuration
from data_platform.catalog.academic_cohort_v6 import V6ProfileVehicle, _evaluate_extended_v4, price_reference_month
from data_platform.catalog.profile_scoring_v3 import configuration as method_configuration, utility
from data_platform.catalog.profile_pilot_v4 import configuration as v4_configuration, fingerprint


class AcademicRecommendationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    snapshot_id: UUID
    scenario: str = Field(default="base", pattern=r"^(low|base|high)$")
    criterion_weights: dict[str, Decimal] | None = None


def recommendation_method():
    method = method_configuration()
    return {"candidate_source": "academic_v6", "profiles": method["profiles"],
            "strategies": ["cost_benefit", "lowest_cost"],
            "cost_scenarios": ["low", "base", "high"],
            "algorithm_version": "academic-v4-live-v1", "minimum_monthly_mileage": 1,
            "personalization_policy": "user-profile-multifactor-v1",
            "alternative_personalization": alternative.method_metadata(),
            "evidence_diagnostics_version": "recommendation-evidence-v1",
            "personalization_components": ["total_cost", "usage_fit", "comfort", "safety", "performance", "efficiency", "legacy_quality"],
            "unavailable_legacy_strategies": ["budget_economy", "balanced", "comfort_space", "best_within_budget"],
            "operationally_active": False, "recommended": False}


def validated_weights(profile, supplied):
    defaults = method_configuration()["profiles"][profile]["weights"]
    values = {k: Decimal(v) for k, v in (defaults if supplied is None else supplied).items()}
    if (set(values) != set(defaults) or any(not v.is_finite() or v < 0 for v in values.values())
            or sum(values.values()) <= 0):
        raise ValueError("Pesos devem cobrir exatamente os critérios do perfil, ser finitos e não negativos, com soma positiva")
    if values.get("transmission", 0) > 0:
        raise ValueError("Peso de transmissão exige preferência explícita; este formulário não oferece essa entrada")
    return values


def live_evaluation(vehicle, profile, scenario, mileage, fuel_price, weights, *, simulation=None, user_scenario=None):
    config = deepcopy(cost_configuration())
    for name, number in (("monthly_km", mileage), ("fuel_price_brl_per_l", fuel_price)):
        config["common_inputs"][name].update(value=str(number), justification="Entrada explícita do usuário nesta recomendação")
    month = price_reference_month(vehicle.fields["reference_month"].value)
    result = _evaluate_extended_v4(vehicle, profile, scenario, month, scenario_config=config)
    if simulation is not None:
        apply_fuel_to_evaluation(result, simulation, user_scenario)
    # Recompose freshly calculated utilities with the same v3/v4 Decimal rule.
    # This is request-local: no mutable global config or frozen method changes.
    method = method_configuration()
    quantum = Decimal(method["precision"]["score"])
    effective = dict.fromkeys(weights, Decimal(0))
    utilities = dict.fromkeys(weights)
    contributions = dict.fromkeys(weights)
    present = [k for k in weights if result["criteria"][k]["value"] is not None and weights[k] > 0]
    denominator = sum((weights[k] for k in present), Decimal(0))
    if denominator:
        for key in present[:-1]:
            effective[key] = (weights[key] / denominator).quantize(
                Decimal(method["precision"]["weight"]), rounding=ROUND_HALF_UP)
        effective[present[-1]] = Decimal(1) - sum(effective.values())
    for key in present:
        field = result["criteria"][key]
        value = Decimal(str(field["value"]))
        if key == "passenger_space" and result["academic_path"] == "academic_habitability_proxy":
            reference = Decimal(v4_configuration()["academic_habitability_proxy"]["reference"])
            raw = Decimal(100) * value / (value + reference)
        elif key in {"safety", "transmission"}:
            raw = value
        else:
            raw = utility(value, method["scales"][key])
        utilities[key] = raw.quantize(quantum, rounding=ROUND_HALF_UP)
        contributions[key] = (utilities[key] * effective[key]).quantize(quantum, rounding=ROUND_HALF_UP)
    result.update(weights=weights, effective_weights=effective, utilities=utilities, contributions=contributions,
                  preview_score=sum((v for v in contributions.values() if v is not None), Decimal(0)) if present else None,
                  price_reference_month=month)
    result["coverage"]["weighted"] = denominator / sum(weights.values())
    result["coverage"]["available"] = present
    result["coverage"]["original_weight_by_nature"] = {
        nature: sum((weights[k] for k in keys), Decimal(0)) / sum(weights.values())
        for nature, keys in result["coverage"]["criteria_by_nature"].items()
    }
    result["comparison_group"] = result["comparison_group"].split(":criteria=")[0] + ":criteria=" + ",".join(sorted(present))
    result["scenario_costs"]["price_reference_month"] = month
    result.pop("baseline_v3_academic_v1", None)  # irrelevant bulk; flags remain explicit above
    return result


def recommend_academic(service, request):
    if request.multifactor_profile:
        alternative.validate_selection(request.multifactor_profile.policy_version, request.candidate_source)
    options = request.academic_options
    profile = request.use_case.value
    weights = validated_weights(profile, options.criterion_weights)
    snapshot = service._snapshot(options.snapshot_id)
    candidates, count = service.repository.vehicles(snapshot.snapshot_id, AcademicFilters(), 60, 0)
    if (count != 60 or len(candidates) != 60 or len({v.catalog_id for v in candidates}) != 60
            or {v.catalog_id for v in candidates} != set(snapshot.inventory_summary["selected_ids"])
            or len({v.fipe_code for v in candidates}) != 60):
        raise AcademicUnavailable("Coorte incompleta")
    documentary = {}
    for record in service.repository.evaluations(snapshot.snapshot_id, profile=profile, scenario=options.scenario):
        checked = service._evaluation(record)
        if record.catalog_id in documentary:
            raise AcademicUnavailable("Cobertura duplicada")
        documentary[record.catalog_id] = checked["academic_test_ready"]
    if set(documentary) != {v.catalog_id for v in candidates} or sum(documentary.values()) != service.profile_counts[profile]:
        raise AcademicUnavailable("Cobertura documental inconsistente")
    rows, excluded, simulations, scenario_errors, diagnostics = [], [], {}, {}, []
    evaluations = {}
    personalization = request.multifactor_profile
    derived = bool(personalization and personalization.policy_version == alternative.VERSION)
    derived_metrics = {}
    user_scenario = personalization.scenario.to_contract() if personalization else None
    for candidate in candidates:
        item = service._item(candidate)
        try:
            vehicle = V6ProfileVehicle.model_validate(candidate.payload)
            simulated = None
            if user_scenario:
                simulated, message = personalized_fuel(vehicle, user_scenario)
                if simulated is None:
                    scenario_errors[candidate.catalog_id] = message
                else:
                    simulations[candidate.catalog_id] = simulated
            # No read of the stored preview_score, monthly TCO or utilities.
            evaluation = live_evaluation(vehicle, profile, options.scenario,
                                         user_scenario.monthly_distance_km if simulated else Decimal(str(request.monthly_mileage)),
                                         simulated.fuel_price_per_liter_brl if simulated else Decimal(str(request.fuel_price)), weights,
                                         simulation=simulated, user_scenario=user_scenario)
        except ValueError:
            raise AcademicUnavailable("Evidência inválida para o motor acadêmico") from None
        reasons = []
        evaluations[candidate.catalog_id] = evaluation
        if not documentary[candidate.catalog_id] or not evaluation["academic_test_ready"]:
            reasons.append("PROFILE_DOCUMENTARY_REQUIREMENTS")
        if item["purchase_price_brl"] > Decimal(str(request.budget)):
            reasons.append("PURCHASE_BUDGET")
        total = evaluation["scenario_monthly_tco_brl"]
        if total is None:
            reasons.append("SCENARIO_TCO_INCOMPLETE")
        elif total > Decimal(str(request.monthly_limit)):
            reasons.append("MONTHLY_BUDGET")
        documentary_detail = documentary_evidence(vehicle, profile, evaluation, documentary[candidate.catalog_id])
        evidence_coverage = personalization_evidence({"vehicle": item}, simulated, personalization.weights.as_mapping()) if personalization else None
        if derived:
            derived_metrics[candidate.catalog_id] = alternative.measurements(
                vehicle, evaluation, simulated, user_scenario, documentary_eligible=documentary[candidate.catalog_id])
            evidence_coverage = alternative.evidence_coverage(derived_metrics[candidate.catalog_id], personalization.weights.as_mapping())
        diagnostics.append({"catalog_id": candidate.catalog_id, "label": candidate.label,
                            "reasons": reasons, "documentary": documentary_detail,
                            "personalization": evidence_coverage})
        if reasons:
            excluded.append({"catalog_id": candidate.catalog_id, "label": candidate.label,
                             "reasons": reasons, "documentary_blockers": evaluation["blockers"],
                             "documentary_diagnostic": documentary_detail})
            continue
        rows.append({"vehicle": {**item, "identity_namespace": "academic_v6", "operational_vehicle_id": None,
                                  "technical_fields": {name: {"value": field.value, "unit": field.unit, "kind": field.kind,
                                                              "sources": [source.model_dump(mode="json") for source in field.sources],
                                                              "applicability": field.applicability, "limitations": field.limitations}
                                                       for name, field in vehicle.fields.items()}},
                     "evaluation": evaluation, "score": evaluation["preview_score"],
                     "monthly_total_cost": total, "monthly_viable": True,
                     "comparison_group": evaluation["comparison_group"],
                     "explanations": [{"criterion": k, "value": evaluation["criteria"][k]["value"],
                                       "nature": evaluation["criteria"][k]["nature"],
                                       "utility": evaluation["utilities"][k], "weight": weights[k],
                                       "effective_weight": evaluation["effective_weights"][k],
                                       "contribution": v}
                                      for k, v in evaluation["contributions"].items() if v is not None]})
    # Recover original calculable subcriteria from all sixty request-local
    # evaluations, before filters. Never normalize against only the survivors.
    if personalization:
        try:
            recovered = calculate_legacy_subcriteria(evaluations)
        except ValueError:
            raise AcademicUnavailable("Entradas de cenário inválidas para os subcritérios originais") from None
        for row in rows:
            identifier = row["vehicle"]["catalog_id"]
            row.update(recovered[identifier])
        for diagnostic in diagnostics:
            identifier = diagnostic["catalog_id"]
            recovered_item = {"vehicle": {}, **recovered[identifier]}
            if not derived:
                diagnostic["personalization"] = personalization_evidence(
                    recovered_item, simulations.get(identifier), personalization.weights.as_mapping())
            diagnostic["legacy_calculations"] = recovered[identifier]
    groups = {}
    for row in rows:
        groups.setdefault(row["comparison_group"], []).append(row)
    for group in groups.values():
        if request.recommendation_strategy.value == "lowest_cost":
            group.sort(key=lambda r: (r["monthly_total_cost"], -r["score"], r["vehicle"]["catalog_id"]))
        else:
            group.sort(key=lambda r: (-r["score"], r["vehicle"]["catalog_id"]))
        for position, row in enumerate(group, 1):
            row["group_position"] = position
    ordered = [r for key in sorted(groups) for r in groups[key]]
    if personalization:
        if derived:
            for key, group in groups.items():
                groups[key] = alternative.score_group(group, derived_metrics, personalization.weights.as_mapping(), user_scenario,
                                                      configuration_id=personalization.configuration_id)
        else:
            personalize_groups(groups, personalization, simulations, scenario_errors, user_scenario)
        ordered = [r for key in sorted(groups) for r in groups[key]]
    ranked_count = sum(r.get("multifactor", {}).get("status") == "ranked" for r in ordered)
    return json_document({
        "candidate_source": "academic_v6", "identity_namespace": "academic_v6",
        "snapshot_id": str(snapshot.snapshot_id), "cohort_fingerprint": snapshot.cohort_fingerprint,
        "algorithm_version": alternative.VERSION if derived else "academic-v4-live-v1",
        "weights_version": alternative.VERSION if derived else method_configuration()["method_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(), "vehicle_type": "car",
        "considered_count": 60, "documentary_eligible_count": sum(documentary.values()),
        "eligible_count": len(ordered), "recommendations": ordered, "excluded": excluded,
        "candidate_diagnostics": diagnostics,
        "exclusion_counts": {reason: sum(reason in row["reasons"] for row in excluded)
                             for reason in ("PROFILE_DOCUMENTARY_REQUIREMENTS", "PURCHASE_BUDGET", "MONTHLY_BUDGET", "SCENARIO_TCO_INCOMPLETE")},
        "has_viable_options": bool(ordered), "ranking_executed": True, "stored_scores_used": False,
        "request_fingerprint": fingerprint(request.model_dump(mode="json")),
        "preferences_applied": request.model_dump(mode="json"),
        "comparison_groups": list(sorted(groups)),
        "baseline_algorithm": "academic-v4-live-v1",
        "multifactor_profile": {"enabled": True, "policy_version": personalization.policy_version,
                               **({"alternative": alternative.method_metadata(),
                                   "configuration": derived_configurations.execution_metadata(personalization.configuration_id, personalization.weights.as_mapping()),
                                   "excluded_dimensions": [key for key, value in personalization.weights.as_mapping().items() if value == 0],
                                   "weights_redistributed": False} if derived else {}),
                               "ranked_count": ranked_count, "original_count": len(ordered) - ranked_count,
                               "scenario_applied_count": len(simulations),
                               "missing_criteria": [{"criterion": key, "label": next(r["label"] for d in diagnostics for r in d["personalization"]["criteria"] if r["criterion"] == key),
                                                     "affected_origin_count": sum(key in d["personalization"]["missing"] for d in diagnostics),
                                                     "affected_result_count": sum(key in r["multifactor"]["evidence_coverage"]["missing"] for r in ordered)}
                                                    for key in personalization.weights.as_mapping()
                                                    if any(key in d["personalization"]["missing"] for d in diagnostics)],
                               "unavailable_messages": sorted(set(scenario_errors.values()))} if personalization else None,
        "empty_reason": "Nenhum veículo satisfaz simultaneamente evidência do perfil, orçamento de compra e limite mensal." if not ordered else None,
        "operationally_active": False, "recommended": False, **service.recommendation_context,
        "limitations": ["TCO de cenário: não é custo observado.", "Habitabilidade é derivada, não espaço interno medido.",
                        "Posições são locais a grupos com a mesma evidência; protocolos distintos não são comparáveis.",
                        "IDs acadêmicos não cadastram veículos em Meu carro ou Despesas.",
                        *([*service.limitations] if service.recommendation_context else [])]})
