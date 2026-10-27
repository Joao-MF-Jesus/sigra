"""Explicit, disabled-by-default academic rubric; never replaces the reference.

Seven historical weight keys are transport slots, not claims that the new
metrics measure comfort, road performance or historical quality.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import os
from pathlib import Path

from app.academic_cohort.legacy_calculations import _inputs as annual_scenario_inputs
from app.academic_cohort.seven_criteria import _fuel_inputs
from app.academic_cohort.derived_mass_power import resolve as resolve_mass_power
from app.academic_cohort import derived_configurations
from app.multifactor_recommendation import normalize_multifactor_weights
from data_platform.catalog.profile_pilot_v4 import fingerprint
from data_platform.catalog.profile_scoring_v3 import utility

VERSION = "academic-derived-seven-v1"
REFERENCE = "user-profile-multifactor-v1"
CONFIG_PATH = Path(__file__).with_name("derived_personalization_v1.json")


def configuration():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def enabled():
    return os.getenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED", "false").strip().lower() == "true"


def validate_selection(policy_version, candidate_source):
    if policy_version != REFERENCE and (policy_version != VERSION or candidate_source != "academic_v6" or not enabled()):
        raise ValueError("A alternativa acadêmica exige seleção explícita, fonte acadêmica e habilitação local; está desabilitada por padrão")


def method_metadata():
    config = configuration()
    return {"version": VERSION, "available": enabled(), "default": False,
            "dimensions": config["dimensions"], "dependencies": config["dependencies"],
            "configuration_registry": derived_configurations.configuration(),
            "contract_fingerprint": fingerprint(config)}


def number(value, *, allow_zero=False):
    if isinstance(value, bool):
        return None
    try:
        value = Decimal(str(value))
        return value if value.is_finite() and (value >= 0 if allow_zero else value > 0) else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def observation(vehicle, name, unit, *, exact=False, boolean=False, allow_zero=False):
    field = vehicle.fields[name]
    allowed = {"exact_variant"} if exact else {"exact_variant", "model_nominal"}
    if field.kind != "observed" or field.unit != unit or field.applicability not in allowed or not field.sources:
        return None
    if boolean:
        return field.value if isinstance(field.value, bool) else None
    value = number(field.value, allow_zero=allow_zero)
    if unit == "count" and value is not None and value != value.to_integral_value():
        return None
    return value


def measurements(vehicle, evaluation, simulation, scenario, *, documentary_eligible):
    """Accept validated evidence, not a cached score or an operational ID."""
    # Complementary evidence affects ONLY this explicit alternative's inputs.
    # The approved vehicle, live v4 evaluation, profile gate and TCO stay intact.
    vehicle, supplementary = resolve_mass_power(vehicle)
    config = configuration()
    out = {}

    def add(key, value, inputs, missing):
        rule = config["dimensions"][key]
        out[key] = {"criterion": key, **rule, "value": value,
                    "inputs_used": inputs, "missing_inputs": missing if value is None else [],
                    "available": value is not None,
                    "requirement_message": "Falta comprovação de " + ", ".join(missing) + "." if value is None else None,
                    "confidence": {"value": None, "status": "not_empirically_calibrated"}}

    def inputs(*names):
        return {name: {**vehicle.fields[name].model_dump(mode="json"),
                       "label": name, "nature": vehicle.fields[name].kind,
                       **({"supplementary_evidence": supplementary[name]} if name in supplementary else {})}
                for name in names}

    fuel = _fuel_inputs({"vehicle": {"technical_fields": {
        k: v.model_dump(mode="json") for k, v in vehicle.fields.items()}}}, simulation, scenario)
    add("total_cost", number(getattr(simulation, "projected_horizon_cost_brl", None)), fuel,
        ["preço e consumos compatíveis com o combustível informado"])
    compatible = documentary_eligible and evaluation["academic_test_ready"]
    add("usage_fit", Decimal(100) if compatible else None,
        {"profile": {"label": "Perfil solicitado", "value": evaluation["profile"], "unit": "text", "nature": "user_input"},
         "compatible": {"label": "Requisitos documentais do perfil satisfeitos", "value": compatible, "unit": "bool", "nature": "derived_academic"},
         "profile_rule_version": {"label": "Método documental de referência", "value": "academic-profile-pilot-v4", "unit": "text", "nature": "method_configuration"}},
        ["requisitos documentais do perfil; não substituídos pela alternativa"])
    add("comfort", observation(vehicle, "cargo_l", "l", allow_zero=True), inputs("cargo_l"),
        ["capacidade do porta-malas da configuração documentada"])
    bags = observation(vehicle, "airbags", "count", exact=True, allow_zero=True)
    abs_value = observation(vehicle, "abs", "bool", exact=True, boolean=True)
    esc = observation(vehicle, "esc", "bool", exact=True, boolean=True)
    safety_inputs = (bags, abs_value, esc)
    safety = (Decimal(100) * (min(bags, Decimal(config["dimensions"]["safety"]["airbag_cap"])) /
              Decimal(config["dimensions"]["safety"]["airbag_cap"]) + int(abs_value) + int(esc)) /
              Decimal(config["dimensions"]["safety"]["divisor"])) if all(v is not None for v in safety_inputs) else None
    add("safety", safety, inputs("airbags", "abs", "esc"),
        [label for label, value in zip(("quantidade total de airbags", "ABS presente ou explicitamente ausente", "ESC presente ou explicitamente ausente"), safety_inputs) if value is None])
    mass = observation(vehicle, "weight_kg", "kg", exact=True)
    power = observation(vehicle, "power_gasoline_cv", "cv", exact=True)
    gasoline = scenario.fuel_strategy.value == "gasoline_c_common" and vehicle.fields["fuel"].value in {"flex", "gasoline"}
    mass_requirement = ("massa em ordem de marcha comprovada para o Focus Fastback SE Plus 2018"
                        if vehicle.id == 80 and supplementary.get("weight_kg", {}).get("status") == "BLOCKED"
                        else "massa em ordem de marcha da versão exata, sem conflito")
    add("performance", mass / power if mass is not None and power is not None and gasoline else None,
        inputs("weight_kg", "power_gasoline_cv", "fuel"),
        [label for label, ok in ((mass_requirement, mass is not None), ("potência com gasolina da versão exata", power is not None), ("cenário com gasolina compatível", gasoline)) if not ok])
    add("efficiency", number(getattr(simulation, "weighted_consumption_km_l", None)),
        {k: v for k, v in fuel.items() if k in {"city_percentage", "highway_percentage", "city_consumption_km_l", "highway_consumption_km_l", "weighted_consumption_km_l"}},
        ["consumos compatíveis com o combustível e percurso informados"])
    costs, missing = {}, []
    for key, label in (("maintenance", "manutenção"), ("depreciation", "desvalorização")):
        try:
            data = annual_scenario_inputs(evaluation, key)
        except ValueError:
            data = None
        if data is None:
            missing.append(label + " com fórmula, unidade e parâmetros explícitos de cenário")
        else:
            costs[key] = {"label": label.capitalize() + " anual estimada", "nature": "scenario_estimate",
                          "value": data["annual_brl"], "unit": "BRL/year",
                          "method_version": data["source"]["method_version"],
                          "formula": "annual_rate * observed_FIPE_price" if data["annual_rate"] is not None else "explicit_fixed_annual_brl",
                          "inputs": deepcopy(data["source"]["inputs"]),
                          "sources": deepcopy(data["source"].get("source_evidence", [])),
                          "source_monthly_component": data["source"]}
    add("legacy_quality", sum((data["value"] for data in costs.values()), Decimal(0)) / 12 if not missing else None,
        costs, missing)
    # Human input labels do not replace field keys, citations, applicability,
    # preserved limitations or original source hashes in the transport.
    labels = {"cargo_l": "Capacidade do porta-malas", "airbags": "Quantidade total de airbags",
              "abs": "ABS", "esc": "Controle de estabilidade", "weight_kg": "Massa da versão",
              "power_gasoline_cv": "Potência com gasolina", "fuel": "Combustível comprovado"}
    for metric in out.values():
        for key, entry in metric["inputs_used"].items():
            entry["label"] = labels.get(key, entry["label"])
    return out


def evidence_coverage(metrics, weights):
    normalized = normalize_multifactor_weights(weights)
    criteria = [{**deepcopy(metric), "requested": normalized[key] > 0, "input_weight": weights[key],
                 "normalized_weight_percentage": normalized[key] * 100}
                for key, metric in metrics.items()]
    requested = [r for r in criteria if r["requested"]]
    evaluated = [r for r in requested if r["available"]]
    return {"policy_version": VERSION, "criteria": criteria, "requested_count": len(requested),
            "evaluated_count": len(evaluated), "complete": len(evaluated) == len(requested),
            "weighted": sum((normalized[r["criterion"]] for r in evaluated), Decimal(0)),
            "missing": [r["criterion"] for r in requested if not r["available"]]}


def score_group(rows, metrics_by_id, weights, scenario, *, configuration_id=None):
    """No mutation of input rows or reference motor; Decimal contributions."""
    config = configuration()
    quantum = Decimal(config["precision"])
    normalized = normalize_multifactor_weights(weights)
    selected_configuration = derived_configurations.execution_metadata(configuration_id, weights)
    output, ranges = [], {}
    for key, rule in config["dimensions"].items():
        if rule["normalization"].startswith("group_minmax"):
            present = [(r["vehicle"]["catalog_id"], metrics_by_id[r["vehicle"]["catalog_id"]][key]["value"])
                       for r in rows if metrics_by_id[r["vehicle"]["catalog_id"]][key]["available"]]
            if present:
                ranges[key] = {"minimum": min(v for _, v in present), "maximum": max(v for _, v in present),
                               "population_ids": sorted(i for i, _ in present), "scope": config["normalization_scope"],
                               "equal_range_rule": config["equal_range_rule"]}
    for position, original in enumerate(rows):
        row = deepcopy(original)
        identifier = row["vehicle"]["catalog_id"]
        coverage = evidence_coverage(metrics_by_id[identifier], weights)
        complete = coverage["complete"]
        calculations = []
        for evidence in coverage["criteria"]:
            key, rule = evidence["criterion"], config["dimensions"][evidence["criterion"]]
            value, score = evidence["value"], None
            if evidence["available"]:
                if rule["normalization"].startswith("absolute"):
                    score = utility(value, rule)
                elif rule["normalization"].startswith("group_minmax"):
                    low, high = ranges[key]["minimum"], ranges[key]["maximum"]
                    score = Decimal(100) if low == high else Decimal(100) * (
                        high - value if rule["direction"] == "lower" else value - low) / (high - low)
                else:
                    score = value
                score = score.quantize(quantum, rounding=ROUND_HALF_UP)
            contribution = (score * normalized[key]).quantize(quantum, rounding=ROUND_HALF_UP) if score is not None else None
            if normalized[key] == 0:
                contribution = Decimal(0)  # explicit exclusion, not a score.
            calculations.append({**evidence, "raw_score": score, "contribution": contribution,
                                 "normalization": ranges.get(key), "policy_version": VERSION,
                                 "calculation_scope": "alternative_ranking" if complete else "diagnostic_only",
                                 "used_in_final_score": complete and normalized[key] > 0})
        final = sum((c["contribution"] for c in calculations), Decimal(0)) if complete else None
        excluded = [{"criterion": key, "label": rule["label"]} for key, rule in config["dimensions"].items() if normalized[key] == 0]
        row["baseline_score"] = row.get("baseline_score", row["score"])
        row["multifactor"] = {"enabled": True, "policy_version": VERSION, "reference_policy_version": REFERENCE,
            "configuration": selected_configuration,
            "status": "ranked" if complete else "unavailable", "final_score": final,
            "reference_order_preserved": not complete, "source_namespace": "academic_v6",
            "scenario_applied": metrics_by_id[identifier]["total_cost"]["available"],
            "scenario": scenario.canonical_payload(), "contract_fingerprint": fingerprint(config),
            "evidence_coverage": coverage, "excluded_dimensions": excluded, "dependencies": config["dependencies"],
            "user_message": None if complete else "Faltam dados de " + ", ".join(c["label"] for c in calculations if c["requested"] and not c["available"]) + ". A ordem de referência foi preservada.",
            "components": [{**c, "component": c["criterion"], "normalized_weight": normalized[c["criterion"]], "source": c["source_method"]} for c in calculations],
            "criterion_calculations": {"version": VERSION, "criteria": calculations, "final_score": final,
                "configuration": selected_configuration,
                "partial_total": None, "weights_redistributed": False,
                "calculated_requested_count": coverage["evaluated_count"], "requested_count": coverage["requested_count"],
                "weighted_coverage": coverage["weighted"], "reference_order_preserved": not complete,
                "excluded_dimensions": excluded, "dependencies": config["dependencies"]}}
        row["score"] = final if complete else row["baseline_score"]
        output.append((position, row))
    output.sort(key=lambda p: (p[1]["multifactor"]["status"] != "ranked",
                               -p[1]["multifactor"]["final_score"] if p[1]["multifactor"]["final_score"] is not None else Decimal(0),
                               p[0], p[1]["vehicle"]["catalog_id"]))
    for position, (_, row) in enumerate(output, 1):
        row["group_position"] = position
    return [row for _, row in output]
