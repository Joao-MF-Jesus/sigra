"""Additive diagnostics for the original seven-criterion policy.

This is not a new ranking rubric. Partial calculations never produce a total,
redistribute a missing weight, or replace an original score with a v4 proxy.
"""
from decimal import Decimal, ROUND_HALF_UP

from app.multifactor_recommendation import (
    MULTIFACTOR_POLICY_VERSION, SCORE_QUANTUM,
    _decimal, _legacy_component_scores, _normalize_cost, _normalize_positive,
    normalize_multifactor_weights, MultifactorRecommendationError,
)
from app.academic_cohort.evidence_diagnostics import personalization_evidence


VERSION = "seven-criteria-diagnostics-v1"
INPUT_LABELS = {
    "score_components.usage_score": "Avaliação do uso escolhido",
    "vehicle.comfort_score": "Avaliação de conforto",
    "vehicle.safety_score": "Avaliação de segurança",
    "vehicle.road_score": "Avaliação de desempenho rodoviário",
    "score_components.maintenance_score": "Manutenção",
    "score_components.reliability_score": "Confiabilidade histórica",
    "score_components.parts_score": "Disponibilidade de peças",
    "score_components.resale_score": "Desvalorização",
}


def _measurement(value):
    try:
        result = _decimal(value, "diagnostic measurement")
        return result if result > 0 else None
    except MultifactorRecommendationError:
        return None


def _input(label, value, unit, nature, sources=()):
    return {"label": label, "value": value, "unit": unit, "nature": nature,
            "sources": list(sources)}


def _fuel_inputs(item, simulation, scenario):
    fields = item["vehicle"].get("technical_fields", {})
    inputs = {
        "monthly_distance_km": _input("Quilometragem mensal", scenario.monthly_distance_km, "km/month", "user_input"),
        "city_percentage": _input("Percurso urbano", scenario.city_percentage, "%", "user_input"),
        "highway_percentage": _input("Percurso rodoviário", scenario.highway_percentage, "%", "user_input"),
        "fuel_price_brl_l": _input("Preço informado do combustível", scenario.manual_fuel_price_brl, "BRL/l", "user_input"),
        "horizon_months": _input("Horizonte de comparação", scenario.horizon_months, "month", "user_input"),
    }
    for route, field in (("city", "consumption_city"), ("highway", "consumption_highway")):
        override = getattr(scenario, route + "_consumption_km_l")
        stored = fields.get(field, {})
        inputs[route + "_consumption_km_l"] = _input(
            "Consumo urbano" if route == "city" else "Consumo rodoviário",
            getattr(simulation, route + "_consumption_km_l", None),
            "km/l", "user_input" if override is not None else stored.get("kind", "unavailable"),
            () if override is not None else stored.get("sources", ()))
    if simulation is not None:
        inputs.update(
            monthly_fuel_cost_brl=_input("Combustível mensal estimado", simulation.monthly_fuel_cost_brl, "BRL/month", "scenario_estimate"),
            projected_horizon_cost_brl=_input("Combustível estimado no horizonte", simulation.projected_horizon_cost_brl, "BRL", "scenario_estimate"),
            weighted_consumption_km_l=_input("Consumo combinado", simulation.weighted_consumption_km_l, "km/l", "derived"),
        )
    return inputs


def criterion_calculations(item, population, simulations, scenario, weights):
    """Expose partial evidence without changing the original motor's output.

    Ranked rows copy the motor's actual score/contribution. For an unranked row,
    fuel/efficiency min/max are diagnostic only, within its comparison group,
    using members with valid scenario inputs. No partial sum is provided.
    """
    normalized = normalize_multifactor_weights(weights)
    simulation = simulations.get(item["vehicle"]["catalog_id"])
    coverage = personalization_evidence(item, simulation, weights)
    originals = _legacy_component_scores(item)
    motor = item.get("multifactor", {})
    ranked = motor.get("status") == "ranked"
    motor_components = {row["component"]: row for row in motor.get("components", ())}
    calculations = []
    for evidence in coverage["criteria"]:
        key = evidence["criterion"]
        available = evidence["available"]
        score = originals[key]
        population_ids, limits = [], None
        inputs = {path: _input(INPUT_LABELS.get(path, path), value, "score/100",
                              "unavailable" if value is None else item.get("calculations", {}).get(
                                  path.split(".", 1)[1], {}).get("nature", "validated_original_input"))
                  for path, value in evidence["inputs"].items()}
        if key in {"total_cost", "efficiency"}:
            inputs = _fuel_inputs(item, simulation, scenario)
            if key == "efficiency":
                inputs = {name: value for name, value in inputs.items()
                          if name in {"monthly_distance_km", "city_percentage", "highway_percentage",
                                      "city_consumption_km_l", "highway_consumption_km_l",
                                      "weighted_consumption_km_l"}}
            attribute = "projected_horizon_cost_brl" if key == "total_cost" else "weighted_consumption_km_l"
            measurements = []
            for member in population:
                identifier = member["vehicle"]["catalog_id"]
                candidate = simulations.get(identifier)
                value = _measurement(getattr(candidate, attribute, None))
                if value is not None:
                    measurements.append(value)
                    population_ids.append(identifier)
            value = _measurement(getattr(simulation, attribute, None))
            available = value is not None and bool(measurements)
            if available:
                limits = {"minimum": min(measurements), "maximum": max(measurements),
                          "population_ids": sorted(population_ids),
                          "scope": "diagnostic_comparison_group",
                          "equal_range_rule": "100 per original method; non-discriminating"}
                score = (_normalize_cost if key == "total_cost" else _normalize_positive)(
                    value, limits["minimum"], limits["maximum"])
        if not available:
            score = None
        contribution = (score * normalized[key]).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP) if score is not None else None
        if normalized[key] == 0:
            contribution = Decimal(0)  # Arithmetic zero, not an imputed score.
        if ranked and key in motor_components and available:
            score = motor_components[key]["raw_score"]
            contribution = motor_components[key]["contribution"]
            if limits:
                ranked_values = [row for row in population if row.get("multifactor", {}).get("status") == "ranked"]
                # The caller supplies transformed rows: this is the motor's exact
                # normalization population, not the larger diagnostic population.
                vals = [getattr(simulations[row["vehicle"]["catalog_id"]], attribute) for row in ranked_values]
                limits.update(minimum=min(vals), maximum=max(vals),
                              population_ids=sorted(row["vehicle"]["catalog_id"] for row in ranked_values),
                              scope="original_motor_ranking")
        calculations.append({**evidence, "available": available,
            "diagnostic_version": VERSION, "policy_version": MULTIFACTOR_POLICY_VERSION,
            "raw_score": score, "contribution": contribution, "inputs_used": inputs,
            "normalization": limits,
            "calculation_scope": "original_motor_ranking" if ranked else "diagnostic_only",
            "used_in_final_score": ranked and normalized[key] > 0,
            "status": "calculated" if available else "unavailable" if normalized[key] > 0 else "not_requested"})
    return {"version": VERSION, "criteria": calculations,
            "final_score": motor.get("final_score") if ranked else None,
            "partial_total": None, "weights_redistributed": False,
            "calculated_requested_count": sum(row["requested"] and row["available"] for row in calculations),
            "requested_count": sum(row["requested"] for row in calculations),
            "weighted_coverage": sum((normalized[row["criterion"]] for row in calculations if row["requested"] and row["available"]), Decimal(0)),
            "reference_order_preserved": not ranked}
