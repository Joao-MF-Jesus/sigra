"""Absolute, cohort-independent utilities for an offline methodological pilot."""
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

from data_platform.catalog.profile_contracts_v3 import VERSION, available
from data_platform.catalog.profile_costs_v3 import cost_evidence, exact

CONFIG_PATH = Path(__file__).with_name("profile_method_v3.json")
CRITERION_FIELDS = {
    "price": ("price_brl",), "urban_fuel": ("consumption_city", "fuel"),
    "footprint": ("length_mm", "width_with_mirrors_mm"),
    "passenger_space": ("rear_legroom_mm", "interior_width_mm"),
    "cargo": ("cargo_l",), "seats": ("seats",), "payload": ("payload_kg",),
    "operating_cost": ("consumption_city", "gasoline_brl_per_l", "maintenance_annual_brl"),
    "highway_consumption": ("consumption_highway", "fuel"),
    "safety": ("airbags", "abs", "esc"),
    "mass_power": ("weight_kg", "power_gasoline_cv"),
    "clearance": ("ground_clearance_mm",),
    "interior_proxy": ("wheelbase_mm", "width_mm"),
    "transmission": ("transmission",),
}


def configuration():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def utility(value, scale):
    """Absolute bounds only. Zero is a valid clamped utility, never missing."""
    if value is None:
        return None
    low, high, value = exact(scale["lower"]), exact(scale["upper"]), exact(value)
    if low < 0 or high <= low or scale["direction"] not in {"higher", "lower"}:
        raise ValueError("Invalid absolute utility scale")
    numerator = value-low if scale["direction"] == "higher" else high-value
    return Decimal(100) * max(Decimal(0), min(Decimal(1), numerator/(high-low)))


def criterion_values(vehicle, costs, scenario):
    output = dict.fromkeys(CRITERION_FIELDS)
    def all_present(key):
        return all(available(vehicle, name) for name in CRITERION_FIELDS[key])
    def value(name):
        return vehicle.fields[name].value
    for criterion, field in (("price", "price_brl"), ("cargo", "cargo_l"), ("seats", "seats"),
                             ("payload", "payload_kg"), ("clearance", "ground_clearance_mm")):
        if all_present(criterion):
            output[criterion] = value(field)
    if all_present("urban_fuel"):
        output["urban_fuel"] = costs["urban_fuel_for_scenario"]
    if all_present("highway_consumption") and value("fuel") in {"gasoline", "flex"}:
        output["highway_consumption"] = value("consumption_highway")
    output["operating_cost"] = costs["proven_operating_cost"]
    for key in ("footprint", "interior_proxy", "passenger_space"):
        if all_present(key):
            a, b = CRITERION_FIELDS[key]
            output[key] = value(a)*value(b)/Decimal(1000000)
    if all_present("safety"):
        output["safety"] = Decimal(100)*(min(value("airbags"), Decimal(6))/Decimal(6) +
                                         Decimal(int(value("abs"))) + Decimal(int(value("esc"))))/Decimal(3)
    if all_present("mass_power"):
        output["mass_power"] = value("weight_kg")/value("power_gasoline_cv")
    if all_present("transmission") and scenario["transmission_preference"] is not None:
        output["transmission"] = Decimal(100 if value("transmission") == scenario["transmission_preference"] else 0)
    return output


def criterion_derivations(vehicle, values):
    """Expose deterministic geometry without relabelling it as observation."""
    output = {}
    if values["footprint"] is not None:
        output["footprint"] = {
            "value": values["footprint"], "unit": "m2",
            "method_version": VERSION,
            "formula": "length_mm * width_with_mirrors_mm / 1_000_000",
            "inputs": {
                "length_mm": vehicle.fields["length_mm"].value,
                "width_with_mirrors_mm": vehicle.fields["width_with_mirrors_mm"].value,
            },
            "reason": None,
        }
    else:
        output["footprint"] = {
            "value": None, "unit": "m2", "method_version": VERSION,
            "formula": None,
            "inputs": {},
            "reason": "Length and width including mirrors are both required",
        }
    if values["passenger_space"] is None:
        output["passenger_space"] = {
            "value": None, "unit": "m2_proxy", "method_version": VERSION,
            "formula": None, "inputs": {},
            "reason": "Rear legroom and measured interior width are required; seats or exterior dimensions are not substitutes",
        }
    return output


def score_vehicle(vehicle, profile, target_month, *, weights=None, config=None, scenario=None):
    config = configuration() if config is None else config
    scenario = config["scenario"] if scenario is None else scenario
    if config["method_version"] != VERSION or profile not in config["profiles"]:
        raise ValueError("Unknown version or profile")
    from datetime import date
    if date.fromisoformat(target_month+"-01").strftime("%Y-%m") != target_month:
        raise ValueError("An explicit comparison month is required")
    definition = config["profiles"][profile]
    weights = definition["weights"] if weights is None else weights
    if set(weights) != set(definition["weights"]):
        raise ValueError("Explicit weight for every profile criterion required")
    weights = {key: exact(number) for key, number in weights.items()}
    total_weight = sum(weights.values(), Decimal(0))
    if total_weight <= 0 or any(weight < 0 for weight in weights.values()):
        raise ValueError("Weights must be nonnegative and not all zero")
    if weights.get("transmission", 0) > 0 and scenario["transmission_preference"] is None:
        raise ValueError("A transmission weight requires an explicit preference")
    costs = cost_evidence(vehicle, scenario)
    values = criterion_values(vehicle, costs, scenario)
    present = [key for key in weights if values[key] is not None]
    temporal_ok = vehicle.fields["reference_month"].value == target_month
    used = [key for key in present if weights[key] > 0] if temporal_ok else []
    denominator = sum((weights[key] for key in used), Decimal(0))
    effective = dict.fromkeys(weights, Decimal(0))
    quantum = Decimal(config["precision"]["score"])
    if denominator:
        for key in used[:-1]:
            effective[key] = (weights[key]/denominator).quantize(Decimal(config["precision"]["weight"]), rounding=ROUND_HALF_UP)
        effective[used[-1]] = Decimal(1)-sum(effective.values(), Decimal(0))
    utilities = dict.fromkeys(weights)
    contributions = dict.fromkeys(weights)
    for key in used:
        utilities[key] = (values[key] if key in {"safety", "transmission"} else utility(values[key], config["scales"][key])).quantize(quantum, rounding=ROUND_HALF_UP)
        contributions[key] = (utilities[key]*effective[key]).quantize(quantum, rounding=ROUND_HALF_UP)
    score = sum((v for v in contributions.values() if v is not None), Decimal(0)) if used else None
    coverage = sum((weights[key] for key in present), Decimal(0))/total_weight
    required_missing = [key for key in definition["required"] if values[key] is None]
    required_any_missing = [group for group in definition["required_any"] if not any(values[key] is not None for key in group)]
    identity_resolved = vehicle.identity_status == "identity_approved"
    scoreability_reasons = []
    if required_missing or required_any_missing:
        scoreability_reasons.append("PROFILE_REQUIRED_EVIDENCE_MISSING")
    diagnostic_score_reasons = []
    if score is None:
        diagnostic_score_reasons.append("NO_COMPARABLE_SCORE")
    eligibility_reasons = []
    if not identity_resolved:
        eligibility_reasons.append("LEGACY_BINDING_NOT_REAUDITED")
    if not temporal_ok:
        eligibility_reasons.append("PRICE_REFERENCE_MONTH_NOT_ALIGNED")
    if vehicle.source_conflicts:
        eligibility_reasons.append("OPEN_SOURCE_CONFLICT")
    if vehicle.human_approval_required and vehicle.human_approval_status != "human_approved":
        eligibility_reasons.append("HUMAN_SUBSTITUTION_APPROVAL_PENDING")
    coverage_reasons = []
    if coverage < exact(config["minimum_weighted_coverage"]):
        coverage_reasons.append("WEIGHTED_COVERAGE_BELOW_0_80")
    profile_scoreable = not scoreability_reasons
    profile_eligible = not eligibility_reasons
    methodology_ready = profile_scoreable and profile_eligible and not coverage_reasons
    recommendation_reasons = []
    if not methodology_ready:
        recommendation_reasons.append("METHODOLOGY_NOT_READY")
    if not costs["is_complete_tco"]:
        recommendation_reasons.append("TCO_INCOMPLETE")
    reasons = eligibility_reasons + scoreability_reasons + coverage_reasons + diagnostic_score_reasons
    return {
        "id": vehicle.id, "label": vehicle.label, "profile": profile,
        "profile_label": definition.get("display_name", profile),
        "preview_score": score, "final_recommendation_score": None,
        "criteria_values": {key: values[key] for key in weights}, "utilities": utilities,
        "contributions": contributions, "original_weights": weights, "effective_weights": effective,
        "available_criteria": present, "used_criteria": used,
        "missing_criteria": [key for key in weights if values[key] is None],
        "required_missing": required_missing, "required_any_missing": required_any_missing,
        "weighted_coverage": coverage, "coverage_not_score": True,
        "confidence": {"value": None, "status": "not_calibrated", "traceable": all(vehicle.fields[name].sources for key in present for name in CRITERION_FIELDS[key])},
        "criterion_evidence": {key: {field: vehicle.fields[field] for field in CRITERION_FIELDS[key]} for key in weights},
        "criterion_derivations": criterion_derivations(vehicle, values),
        "costs": costs, "source_conflicts": vehicle.source_conflicts,
        "identity_resolved": identity_resolved,
        "partial_coverage_candidate": bool(present),
        "profile_scoreable": profile_scoreable,
        "profile_eligible": profile_eligible,
        "methodology_ready": methodology_ready,
        "tco_complete": costs["is_complete_tco"],
        "recommendable": methodology_ready and costs["is_complete_tco"],
        "recommended": False,
        "scoreability_reasons": scoreability_reasons,
        "diagnostic_score_reasons": diagnostic_score_reasons,
        "eligibility_reasons": eligibility_reasons,
        "coverage_reasons": coverage_reasons,
        "recommendation_reasons": recommendation_reasons,
        "gate_reasons": reasons,
        "operationally_active": False,
        "limitations": config["limitations"] + vehicle.provenance.get("technical_limitations", []),
        "nominal_measurement_scope": config["nominal_scope"],
    }


def score_cohort(vehicles, profile, target_month, **options):
    identifiers = [vehicle.id for vehicle in vehicles]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate physical identity in cohort")
    months = {v.fields["reference_month"].value for v in vehicles if available(v, "price_brl")}
    if months - {target_month}:
        raise ValueError("Mixed or mismatched FIPE month: pooled preview forbidden")
    rows = [score_vehicle(v, profile, target_month, **options) for v in vehicles]
    ranked = sorted((r for r in rows if r["preview_score"] is not None), key=lambda r: (-r["preview_score"], r["id"]))
    top = ranked[:10]
    recommendable = [r for r in ranked if r["recommendable"]]
    profile_config = options.get("config") or configuration()
    return {"profile": profile, "profile_label": profile_config["profiles"][profile].get("display_name", profile),
            "target_month": target_month, "records": rows,
            "ranking": ranked, "diagnostic_preview_ranking": ranked, "top10": top,
            "top10_boundary_ids": [r["id"] for r in ranked if top and r["preview_score"] >= top[-1]["preview_score"]],
            "methodology_ready_ids": [r["id"] for r in rows if r["methodology_ready"]],
            "recommendable_ids": [r["id"] for r in recommendable],
            "recommendation_ranking": [], "recommended_ids": [], "recommendation_executed": False,
            "rank_scope": "Exploratory partial utilities; differing evidence masks are NOT equal suitability. ID sorts display ties only."}
