"""Recover calculable original subcriteria, never manufacture historical quality.

Normalization uses the entire candidate origin before documentary/financial
filters, as recommender.recommend does. Scenario estimates remain estimates.
The four-input quality mean is still unavailable without reliability and parts.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from app.recommender import clamp_score, normalize_cost

VERSION = "legacy-scenario-subcriteria-v1"


def _number(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a cost/rate")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid cost/rate") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Finite nonnegative cost/rate required")
    return result


def _inputs(evaluation, component):
    evidence = evaluation["scenario_costs"]["components"].get(component)
    if not evidence or evidence.get("value") is None:
        return None
    if (evidence.get("unit") != "BRL/month"
            or evidence.get("nature") != "scenario_estimate"
            or evidence.get("method_version") != "academic_cost_scenario_v1"):
        raise ValueError("Unexpected scenario evidence contract")
    inputs = evidence["inputs"]
    rate = inputs.get("annual_rate")
    if rate is not None:
        if rate["unit"] != "fraction/year" or rate["nature"] != "scenario_parameter":
            raise ValueError("Annual rate unit/nature mismatch")
        value = _number(rate["value"])
        if value > 1:
            raise ValueError("Annual rate must be a fraction")
        price = inputs["price_brl"]
        if price["unit"] != "BRL" or price["nature"] != "observed":
            raise ValueError("Observed FIPE price is required")
        annual = value * _number(price["value"])
    else:
        fixed = inputs.get("fixed_annual_brl")
        if component != "maintenance" or not fixed:
            raise ValueError("Missing annual rate")
        if fixed["unit"] != "BRL/year" or fixed["nature"] != "scenario_parameter":
            raise ValueError("Fixed annual amount unit/nature mismatch")
        annual, value = _number(fixed["value"]), None
    # Use unrounded annual inputs, not a rounded monthly amount times twelve.
    return {"annual_brl": annual, "annual_rate": value, "source": deepcopy(evidence)}


def calculate_legacy_subcriteria(evaluations):
    inputs = {identifier: {key: _inputs(evaluation, key)
                          for key in ("maintenance", "depreciation")}
              for identifier, evaluation in evaluations.items()}
    ranges = {}
    for key, field in (("maintenance", "annual_brl"), ("depreciation", "annual_rate")):
        values = [float(row[key][field]) for row in inputs.values() if row[key] is not None]
        ranges[key] = (min(values), max(values)) if values else None
    output = {}
    for identifier, row in inputs.items():
        scores = dict.fromkeys(("usage_score", "maintenance_score", "reliability_score", "parts_score", "resale_score"))
        calculations = {}
        for component, score_key in (("maintenance", "maintenance_score"), ("depreciation", "resale_score")):
            data = row[component]
            if data is None:
                calculations[score_key] = {"score": None, "nature": "unavailable", "reason": "annual_scenario_input_unavailable"}
                continue
            if component == "maintenance":
                annual = float(data["annual_brl"])
                relative = normalize_cost(annual, *ranges[component])
                absolute = clamp_score(100 - annual / 70)
                # Original documented fallback: maintenance_index=absolute when
                # no admissible parts feedback exists. No feedback is fabricated.
                raw = relative * .25 + absolute * .35 + absolute * .40
                formula = "0.25 * normalize_cost(annual_maintenance) + 0.35 * clamp(100-annual_maintenance/70) + 0.40 * maintenance_index"
            else:
                relative = normalize_cost(float(data["annual_rate"]), *ranges[component])
                absolute, raw = None, relative
                formula = "normalize_cost(annual_depreciation_rate)"
            score = Decimal(str(round(clamp_score(raw), 2)))
            scores[score_key] = score
            calculations[score_key] = {"score": score, "unit": "score/100", "nature": "scenario_estimate",
                "method_version": VERSION, "original_method": "app.recommender.build_score_components",
                "formula": formula, "inputs": data, "normalization_range": ranges[component],
                "normalization_population": sorted(evaluations), "relative_score": relative,
                "absolute_score": absolute, "maintenance_index": absolute if component == "maintenance" else None,
                "feedback_used": False,
                "equal_range_rule": "100 per original normalize_cost; no discrimination",
                "historical_observation_claimed": False}
        output[identifier] = {"score_components": scores, "calculations": calculations,
                              "quality_complete": False,
                              "missing_quality_inputs": [key for key in ("maintenance_score", "reliability_score", "parts_score", "resale_score")
                                                         if scores[key] is None]}
    return output
