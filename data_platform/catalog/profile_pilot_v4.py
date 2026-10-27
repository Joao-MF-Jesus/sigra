"""Additive, pure offline academic preview. No adapters, database or publication."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

from data_platform.catalog.academic_cost_scenario import evaluate_vehicle as baseline_vehicle
from data_platform.catalog.evidence_analysis import similarity
from data_platform.catalog.profile_contracts_v3 import ProfileVehicle
from data_platform.catalog.profile_safety_v4 import safety_evidence
from data_platform.catalog.profile_scoring_v3 import CRITERION_FIELDS, configuration as v3_configuration, utility

VERSION = "academic-profile-pilot-v4"
CONFIG_PATH = Path(__file__).with_name("profile_method_v4.json")


def configuration():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def fingerprint(value):
    def encode(item):
        if isinstance(item, Decimal):
            return str(item)
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        raise TypeError(type(item).__name__)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=encode)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _positive(value):
    if isinstance(value, (float, bool)):
        raise ValueError("Exact Decimal parameter required")
    result = Decimal(value)
    if not result.is_finite() or result <= 0:
        raise ValueError("Positive finite parameter required")
    return result


def _input_valid(observation, unit):
    return bool(observation.kind == "observed" and observation.unit == unit
                and observation.applicability in {"exact_variant", "model_nominal"}
                and observation.value is not None and observation.value > 0)


def habitability_evidence(vehicle, *, divide_by_places=True):
    """No mutation of the v3 passenger_space field or any observed evidence."""
    method = configuration()["academic_habitability_proxy"]
    direct = ("rear_legroom_mm", "interior_width_mm")
    if all(_input_valid(vehicle.fields[key], "mm") for key in direct):
        inputs = {key: vehicle.fields[key].model_dump(mode="json") for key in direct}
        return {"path": "measured_interior_inputs", "value": vehicle.fields[direct[0]].value
                * vehicle.fields[direct[1]].value / Decimal(1000000), "unit": "m2_proxy",
                "nature": "derived_academic", "formula": "rear_legroom_mm * interior_width_mm / 1000000",
                "method_version": "catalog-profile-evidence-v3", "inputs": inputs,
                "input_coverage": Decimal(1), "reason": None,
                "confidence": {"value": None, "status": "measured_inputs_not_calibrated_comfort"}}
    inputs = {key: vehicle.fields[key].model_dump(mode="json") for key in method["inputs"]}
    valid = [key for key, unit in method["inputs"].items() if _input_valid(vehicle.fields[key], unit)]
    if len(valid) != len(inputs):
        return {"path": "unavailable", "value": None, "unit": method["unit"], "nature": "unavailable",
                "inputs": inputs, "input_coverage": Decimal(len(valid)) / Decimal(len(inputs)),
                "reason": "POSITIVE_OBSERVED_HABITABILITY_INPUTS_REQUIRED",
                "confidence": {"value": None, "status": "insufficient_inputs"}}
    value = vehicle.fields["wheelbase_mm"].value * vehicle.fields["width_mm"].value / Decimal(1000000)
    if divide_by_places:
        value /= vehicle.fields["seats"].value
    return {"path": "academic_habitability_proxy", "value": value,
            "unit": method["unit"] if divide_by_places else "m2",
            "nature": "derived_academic", "method_version": VERSION,
            "formula": method["formula"] if divide_by_places else "wheelbase_mm * width_mm / 1000000",
            "inputs": inputs, "input_coverage": Decimal(1), "reason": None,
            "sensitivity_only": not divide_by_places,
            "confidence": {"value": None, "status": method["confidence"]},
            "limitations": method["limitations"], "measured_interior_space": False}


def _inherited_evidence(vehicle, criterion, value, baseline, method):
    inputs = {key: vehicle.fields[key].model_dump(mode="json") for key in CRITERION_FIELDS[criterion]}
    if criterion in {"urban_fuel", "operating_cost"}:
        evidence = (baseline["academic_costs"]["components"]["fuel"] if criterion == "urban_fuel"
                    else baseline["academic_costs"]["scenario_total"])
        return {**deepcopy(evidence), "inputs_evidence": inputs,
                "components": deepcopy(baseline["academic_costs"]["components"]) if criterion == "operating_cost" else None}
    if value is None:
        return {"value": None, "nature": "unavailable", "inputs": inputs,
                "reason": "INHERITED_CRITERION_EVIDENCE_UNAVAILABLE"}
    single_observed = len(inputs) == 1 and all(row["kind"] == "observed" for row in inputs.values())
    formulas = {
        "footprint": "length_mm * width_with_mirrors_mm / 1000000",
        "interior_proxy": "wheelbase_mm * width_mm / 1000000",
        "mass_power": "weight_kg / power_gasoline_cv",
        "highway_consumption": "PBEV consumption_highway for compatible gasoline/flex fuel",
        "transmission": "explicit preference match only",
    }
    return {"value": value, "nature": "observed" if single_observed else "derived_academic",
            "unit": method["scales"][criterion]["unit"], "inputs": inputs, "reason": None,
            "formula": formulas.get(criterion, "identity of evidenced field"),
            "method_version": "catalog-profile-evidence-v3"}


def evaluate_vehicle(vehicle, profile, scenario, target_month, *, records=(), document_directory=None,
                     scenario_config=None, proxy_reference=None, proxy_weight_multiplier="1",
                     divide_by_places=True):
    # Revalidate even model_copy-constructed input; invalid units never enter scoring.
    vehicle = ProfileVehicle.model_validate(vehicle.model_dump())
    method = v3_configuration()
    config = configuration()
    baseline = baseline_vehicle(vehicle, profile, scenario, target_month, config=scenario_config)
    values = dict(baseline["academic_criteria_values"])
    definition = method["profiles"][profile]
    weights = {key: Decimal(value) for key, value in definition["weights"].items()}
    evidence = {key: _inherited_evidence(vehicle, key, value, baseline, method) for key, value in values.items()}
    path = "inherited_academic_v1"
    comparison_group = path
    if profile == "app":
        item = habitability_evidence(vehicle, divide_by_places=divide_by_places)
        evidence["passenger_space"] = item
        values["passenger_space"] = item["value"]
        path = comparison_group = item["path"]
        if path == "academic_habitability_proxy":
            weights["passenger_space"] *= _positive(proxy_weight_multiplier)
    if profile in {"familia", "estrada"}:
        item = safety_evidence(vehicle, records, document_directory)
        evidence["safety"] = item
        values["safety"] = item["value"]
        path = item["path"]
        comparison_group = item.get("comparison_group", "unavailable")
    present = [key for key in weights if values[key] is not None and weights[key] > 0]
    missing = [key for key in definition["required"] if values[key] is None]
    missing_any = [group for group in definition["required_any"] if not any(values[key] is not None for key in group)]
    denominator = sum((weights[key] for key in present), Decimal(0))
    effective = dict.fromkeys(weights, Decimal(0))
    quantum = Decimal(method["precision"]["score"])
    if denominator:
        for key in present[:-1]:
            effective[key] = (weights[key] / denominator).quantize(Decimal(method["precision"]["weight"]), rounding=ROUND_HALF_UP)
        effective[present[-1]] = Decimal(1) - sum(effective.values(), Decimal(0))
    utilities, contributions = dict.fromkeys(weights), dict.fromkeys(weights)
    for key in present:
        if key == "passenger_space" and path == "academic_habitability_proxy":
            default_reference = (config["academic_habitability_proxy"]["reference"] if divide_by_places
                                 else config["sensitivity"]["undivided_reference_m2"])
            reference = _positive(default_reference if proxy_reference is None else proxy_reference)
            raw = Decimal(100) * values[key] / (values[key] + reference)
            evidence[key]["utility_reference"] = reference
            evidence[key]["utility_reference_unit"] = evidence[key]["unit"]
            evidence[key]["utility_formula"] = config["academic_habitability_proxy"]["utility_formula"]
        elif key in {"safety", "transmission"}:
            raw = values[key]
        else:
            raw = utility(values[key], method["scales"][key])
        utilities[key] = raw.quantize(quantum, rounding=ROUND_HALF_UP)
        contributions[key] = (utilities[key] * effective[key]).quantize(quantum, rounding=ROUND_HALF_UP)
    scoreable = not missing and not missing_any
    ready = bool(baseline["identity_resolved"] and baseline["profile_eligible"] and scoreable and baseline["scenario_tco_complete"])
    blockers = [b for b in baseline["blockers"] if b != "PROFILE_REQUIRED_EVIDENCE_MISSING"]
    if missing or missing_any:
        blockers.append("V4_REQUIRED_EVIDENCE_UNAVAILABLE")
    for key in missing:
        if evidence[key].get("reason"):
            blockers.append(evidence[key]["reason"])
    score = sum((x for x in contributions.values() if x is not None), Decimal(0)) if present else None
    by_nature = {nature: [key for key, item in evidence.items() if item["nature"] == nature]
                 for nature in ("observed", "derived_academic", "scenario_estimate", "unavailable")}
    # Methodology/observed TCO come only from the unchanged baseline, never v4 readiness.
    return {
        "version": VERSION, "id": vehicle.id, "vehicle": vehicle.label, "profile": profile, "scenario": scenario,
        "identity_resolved": baseline["identity_resolved"], "profile_eligible": baseline["profile_eligible"],
        "profile_scoreable": scoreable, "academic_test_ready": ready,
        "methodology_ready": baseline["methodology_ready"], "observed_tco_complete": baseline["observed_tco_complete"],
        "scenario_tco_complete": baseline["scenario_tco_complete"], "scenario_monthly_tco_brl": baseline["scenario_monthly_tco_brl"],
        "operationally_active": False, "recommended": False, "operational_ranking": [],
        "academic_path": path, "comparison_group": comparison_group + ":criteria=" + ",".join(sorted(present)),
        "preview_score": score, "criteria": evidence, "utilities": utilities, "contributions": contributions,
        "weights": weights, "effective_weights": effective,
        "coverage": {"weighted": denominator / sum(weights.values(), Decimal(0)),
                     "criteria_by_nature": by_nature,
                     "original_weight_by_nature": {nature: sum((weights[key] for key in keys), Decimal(0))
                                                    / sum(weights.values(), Decimal(0)) for nature, keys in by_nature.items()},
                     "required_missing": missing, "required_any_missing": missing_any,
                     "available": present, "missing": [key for key in weights if values[key] is None]},
        "confidence": {"value": None, "status": "descriptive_traceability_not_statistical_confidence",
                       "proxy_used": path == "academic_habitability_proxy"},
        "blockers": list(dict.fromkeys(blockers)), "scenario_costs": baseline["academic_costs"],
        "field_inventory": {key: field.model_dump(mode="json") for key, field in vehicle.fields.items()},
        "observed_field_names": [key for key, field in vehicle.fields.items() if field.kind == "observed"],
        "derived_criterion_names": by_nature["derived_academic"],
        "baseline_v3_academic_v1": baseline,
    }


def rankings(rows):
    groups = {}
    for row in rows:
        if row["academic_test_ready"] and row["preview_score"] is not None:
            groups.setdefault(row["comparison_group"], []).append(row)
    result = {}
    for key, candidates in sorted(groups.items()):
        ordered = sorted(candidates, key=lambda row: (-row["preview_score"], row["id"]))
        boundary = ordered[min(9, len(ordered) - 1)]["preview_score"]
        result[key] = {
            "ranking": [{"id": row["id"], "preview_score": row["preview_score"]} for row in ordered],
            "top10_boundary_ids": [row["id"] for row in ordered if row["preview_score"] >= boundary],
            "ties": [{"score": value, "ids": [r["id"] for r in ordered if r["preview_score"] == value]}
                     for value in sorted({r["preview_score"] for r in ordered}, reverse=True)
                     if sum(r["preview_score"] == value for r in ordered) > 1],
            "diagnostic_only": True,
        }
    return result


def compare_groups(left, right):
    empty = {"ranking": [], "top10_boundary_ids": []}
    return {key: similarity(left.get(key, empty), right.get(key, empty)) for key in sorted(left.keys() | right.keys())}


def evaluate_cohort(vehicles, target_month, *, records=(), document_directory=None, scenario_config=None):
    vehicles = tuple(vehicles)
    if len({v.id for v in vehicles}) != len(vehicles):
        raise ValueError("Duplicate vehicle ID")
    if any(v.fields["reference_month"].value != target_month for v in vehicles):
        raise ValueError("Target FIPE month mismatch")
    config = configuration()
    records = tuple(records or config["safety"]["records"])
    profiles = v3_configuration()["profiles"]
    scenarios = {}
    for scenario in ("low", "base", "high"):
        reports = {}
        for profile in profiles:
            rows = [evaluate_vehicle(v, profile, scenario, target_month, records=records,
                                     document_directory=document_directory, scenario_config=scenario_config) for v in vehicles]
            reports[profile] = {"rows": rows, "diagnostic_rankings": rankings(rows), "counts": {
                key: sum(bool(row[key]) for row in rows) for key in (
                    "identity_resolved", "profile_scoreable", "profile_eligible", "methodology_ready",
                    "observed_tco_complete", "scenario_tco_complete", "academic_test_ready", "operationally_active", "recommended")}}
        scenarios[scenario] = reports
    sensitivity = {}
    reference_ranks = scenarios["base"]["app"]["diagnostic_rankings"]
    variants = [("reference=" + value, {"proxy_reference": value}) for value in config["sensitivity"]["proxy_reference_values"]]
    variants += [("weight_multiplier=" + value, {"proxy_weight_multiplier": value}) for value in config["sensitivity"]["proxy_weight_multipliers"]]
    variants.append(("undivided_external_envelope_m2", {"divide_by_places": False}))
    for name, options in variants:
        rows = [evaluate_vehicle(v, "app", "base", target_month, scenario_config=scenario_config, **options) for v in vehicles]
        sensitivity[name] = {"diagnostic_rankings": rankings(rows), "comparison": compare_groups(reference_ranks, rankings(rows)),
                             "ready_ids": [r["id"] for r in rows if r["academic_test_ready"]],
                             "specification": options}
    cost_sensitivity = {profile: {name: compare_groups(scenarios["base"][profile]["diagnostic_rankings"], scenarios[name][profile]["diagnostic_rankings"])
                                 for name in ("low", "high")} for profile in profiles}
    ready_ids = sorted({r["id"] for report in scenarios["base"].values() for r in report["rows"] if r["academic_test_ready"]})
    return {"version": VERSION, "scenario_reports": scenarios, "distinct_ready_ids": ready_ids,
            "habitability_sensitivity": sensitivity, "cost_sensitivity": cost_sensitivity,
            "operational_ranking": [], "operationally_active": 0, "recommended": 0,
            "configuration_sha256": hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()}
