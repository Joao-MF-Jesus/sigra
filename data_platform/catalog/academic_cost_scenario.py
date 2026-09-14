"""Offline academic TCO scenarios; never operational evidence or publication."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

from data_platform.catalog.profile_contracts_v3 import available
from data_platform.catalog.profile_costs_v3 import COMPONENTS, cost_evidence, exact
from data_platform.catalog.profile_scoring_v3 import configuration as profile_configuration
from data_platform.catalog.profile_scoring_v3 import score_vehicle, utility

VERSION = "academic_cost_scenario_v1"
CONFIG_PATH = Path(__file__).with_name("academic_cost_scenario_v1.json")
MONEY = Decimal("0.01")
RATE_UNIT = "fraction/year"
FIXED_UNIT = "BRL/year"
PARAMETER_MODES = {"rate_of_fipe_price", "fixed_annual_brl"}


def configuration(path=CONFIG_PATH):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_configuration(config)
    return config


def _collection(value):
    return value if isinstance(value, list) else []


def _decimal(value, label):
    try:
        number = exact(value)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ValueError(f"{label} requires an exact finite Decimal-compatible value") from exc
    if number < 0:
        raise ValueError(f"{label} cannot be negative")
    return number


def validate_configuration(config):
    required = {"version", "mode", "target_month", "common_inputs", "methods", "scenarios",
                "diagnostic_derivations", "academic_profile_criterion_overrides",
                "critical_criteria_source", "coverage_sensitivity_thresholds", "guardrails"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("Academic scenario contract fields differ")
    if config["version"] != VERSION or config["mode"] != "offline_academic_sensitivity_preview":
        raise ValueError("Academic scenario version or mode differs")
    common = config["common_inputs"]
    if set(common) != {"monthly_km", "fuel_price_brl_per_l"}:
        raise ValueError("Explicit common scenario inputs required")
    km = _decimal(common["monthly_km"].get("value"), "monthly_km")
    fuel_price = _decimal(common["fuel_price_brl_per_l"].get("value"), "fuel_price_brl_per_l")
    if km <= 0 or fuel_price <= 0:
        raise ValueError("Distance and fuel price must be positive")
    if common["monthly_km"].get("unit") != "km/month" or common["fuel_price_brl_per_l"].get("unit") != "BRL/l":
        raise ValueError("Academic common-input unit mismatch")
    if any(item.get("nature") != "scenario_parameter" or not item.get("justification") for item in common.values()):
        raise ValueError("Academic parameters require nature and justification")
    if set(config["methods"]) != set(COMPONENTS):
        raise ValueError("Exactly five TCO methods required")
    for component, method in config["methods"].items():
        if method.get("unit") != "BRL/month" or method.get("nature") != "scenario_estimate":
            raise ValueError("Academic method nature or unit mismatch: " + component)
        if not method.get("methodological_origin") or not _collection(method.get("required_vehicle_fields")):
            raise ValueError("Academic method provenance is incomplete: " + component)
    expected_derivation = {
        "unit": "m2", "nature": "derived",
        "formula": "length_mm * body_width_mm / 1000000",
        "required_vehicle_fields": ["length_mm", "width_mm"],
        "accepted_for_profile_criteria": [],
    }
    derivations = config["diagnostic_derivations"]
    if set(derivations) != {"body_footprint_m2"}:
        raise ValueError("Academic diagnostic derivation scope differs")
    body_footprint = derivations["body_footprint_m2"]
    if any(body_footprint.get(key) != value for key, value in expected_derivation.items()):
        raise ValueError("Body footprint derivation contract differs")
    if not body_footprint.get("methodological_origin"):
        raise ValueError("Body footprint derivation requires methodological origin")
    expected_override = {
        "source": "scenario_monthly_tco_brl", "unit": "BRL/month",
        "nature": "scenario_estimate", "allowed_gate": "academic_test_ready",
        "operational_gate_allowed": False,
    }
    overrides = config["academic_profile_criterion_overrides"]
    if set(overrides) != {"trabalho"} or set(overrides["trabalho"]) != {"operating_cost"}:
        raise ValueError("Academic profile override scope differs")
    operating_cost_override = overrides["trabalho"]["operating_cost"]
    if any(operating_cost_override.get(key) != value for key, value in expected_override.items()):
        raise ValueError("Academic operating-cost override differs")
    if not operating_cost_override.get("methodological_origin"):
        raise ValueError("Academic operating-cost override requires methodological origin")
    if set(config["scenarios"]) != {"low", "base", "high"}:
        raise ValueError("Low, base and high scenarios are mandatory")
    for scenario_name, parameters in config["scenarios"].items():
        if set(parameters) - (set(COMPONENTS) - {"fuel"}):
            raise ValueError("Unknown annual scenario component: " + scenario_name)
        for component, parameter in parameters.items():
            if set(parameter) != {"mode", "value", "unit"}:
                raise ValueError("Explicit annual parameter fields required")
            mode = parameter["mode"]
            if mode not in PARAMETER_MODES:
                raise ValueError("Unsupported academic parameter mode")
            if component in {"ipva", "depreciation"} and mode != "rate_of_fipe_price":
                raise ValueError(component + " requires the declared annual-rate method")
            expected_unit = RATE_UNIT if mode == "rate_of_fipe_price" else FIXED_UNIT
            if parameter["unit"] != expected_unit:
                raise ValueError("Academic annual parameter unit mismatch")
            value = _decimal(parameter["value"], scenario_name + "." + component)
            if mode == "rate_of_fipe_price" and value > Decimal(1):
                raise ValueError("Academic annual rates must be fractions from zero through one")
    thresholds = [_decimal(value, "coverage threshold") for value in config["coverage_sensitivity_thresholds"]]
    if not thresholds or thresholds != sorted(set(thresholds)) or thresholds[-1] > Decimal(1):
        raise ValueError("Coverage sensitivity thresholds must be unique ascending fractions")
    expected_guardrails = {
        "operational_activation_allowed": False, "publication_allowed": False,
        "recommendation_ranking_executed": False, "safety_estimation_allowed": False,
        "missing_is_zero": False, "parameters_calibrated_to_desired_order": False,
        "legacy_vehicle_values_modified": False,
    }
    if config["guardrails"] != expected_guardrails:
        raise ValueError("Academic guardrails cannot be weakened")
    return config


def _money(value):
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _unavailable_component(component, reason, method):
    return {
        "value": None, "unit": "BRL/month", "nature": "unavailable",
        "formula": None, "method_version": VERSION,
        "methodological_origin": method["methodological_origin"],
        "reason": reason, "inputs": {}, "source_evidence": [],
    }


def _source_evidence(observation):
    return [
        {
            "provider": source.provider, "sha256": source.sha256,
            "document": source.document, "locator": source.locator,
            "collected_at": source.collected_at.isoformat(),
        }
        for source in observation.sources
    ]


def body_footprint_evidence(vehicle, *, config=None):
    """Derive body area for diagnostics without claiming width with mirrors."""
    config = configuration() if config is None else validate_configuration(deepcopy(config))
    method = config["diagnostic_derivations"]["body_footprint_m2"]
    missing = [name for name in method["required_vehicle_fields"] if not available(vehicle, name)]
    if missing:
        return {
            "value": None, "unit": method["unit"], "nature": "unavailable",
            "formula": None, "method_version": VERSION,
            "methodological_origin": method["methodological_origin"],
            "inputs": {}, "input_evidence_hashes": {},
            "accepted_for_profile_criteria": [],
            "reason": "Required body dimension evidence is unavailable: " + ", ".join(missing),
        }
    length = exact(vehicle.fields["length_mm"].value)
    body_width = exact(vehicle.fields["width_mm"].value)
    if length <= 0 or body_width <= 0:
        raise ValueError("Body footprint requires positive millimetre dimensions")
    inputs = {}
    hashes = {}
    for field_name, value in (("length_mm", length), ("body_width_mm", body_width)):
        vehicle_field = "width_mm" if field_name == "body_width_mm" else field_name
        observation = vehicle.fields[vehicle_field]
        evidence = _source_evidence(observation)
        inputs[field_name] = {
            "value": value, "unit": "mm", "nature": observation.kind,
            "source_evidence": evidence,
        }
        hashes[field_name] = [source["sha256"] for source in evidence]
    return {
        "value": length * body_width / Decimal(1000000),
        "unit": method["unit"], "nature": method["nature"],
        "formula": method["formula"], "method_version": VERSION,
        "methodological_origin": method["methodological_origin"],
        "inputs": inputs, "input_evidence_hashes": hashes,
        "accepted_for_profile_criteria": list(method["accepted_for_profile_criteria"]),
        "reason": None,
    }


def scenario_cost_evidence(vehicle, scenario_name, *, config=None):
    config = configuration() if config is None else validate_configuration(deepcopy(config))
    if scenario_name not in config["scenarios"]:
        raise ValueError("Unknown academic scenario")
    monthly_km = _decimal(config["common_inputs"]["monthly_km"]["value"], "monthly_km")
    fuel_price = _decimal(config["common_inputs"]["fuel_price_brl_per_l"]["value"], "fuel_price_brl_per_l")
    methods = config["methods"]
    output = {component: _unavailable_component(component, "Required evidence or scenario parameter is unavailable", methods[component])
              for component in COMPONENTS}

    if available(vehicle, "consumption_city") and available(vehicle, "fuel"):
        if vehicle.fields["fuel"].value in {"gasoline", "flex"}:
            consumption = exact(vehicle.fields["consumption_city"].value)
            if consumption <= 0:
                raise ValueError("PBEV urban consumption must be positive")
            output["fuel"] = {
                "value": _money(monthly_km / consumption * fuel_price),
                "unit": "BRL/month", "nature": "scenario_estimate",
                "formula": methods["fuel"]["formula"], "method_version": VERSION,
                "methodological_origin": methods["fuel"]["methodological_origin"], "reason": None,
                "inputs": {
                    "monthly_km": {"value": monthly_km, "unit": "km/month", "nature": "scenario_parameter"},
                    "consumption_city": {"value": consumption, "unit": "km/l", "nature": vehicle.fields["consumption_city"].kind},
                    "fuel_price_brl_per_l": {"value": fuel_price, "unit": "BRL/l", "nature": "scenario_parameter"},
                },
                "source_evidence": _source_evidence(vehicle.fields["consumption_city"]),
            }
        else:
            output["fuel"]["reason"] = "The gasoline scenario is incompatible with the evidenced vehicle fuel"
    else:
        output["fuel"]["reason"] = "PBEV urban consumption and evidenced fuel are both required"

    price = exact(vehicle.fields["price_brl"].value) if available(vehicle, "price_brl") else None
    for component in COMPONENTS[1:]:
        parameter = config["scenarios"][scenario_name].get(component)
        if parameter is None:
            output[component]["reason"] = "Required academic scenario parameter is absent"
            continue
        mode = parameter["mode"]
        value = _decimal(parameter["value"], scenario_name + "." + component)
        if mode == "rate_of_fipe_price":
            if price is None:
                output[component]["reason"] = "FIPE price evidence is required by the annual-rate method"
                continue
            monthly = price * value / Decimal(12)
            formula = methods[component]["formula"] if "formula" in methods[component] else methods[component]["formula_rate"]
            inputs = {
                "price_brl": {"value": price, "unit": "BRL", "nature": vehicle.fields["price_brl"].kind},
                "annual_rate": {"value": value, "unit": RATE_UNIT, "nature": "scenario_parameter"},
            }
            sources = _source_evidence(vehicle.fields["price_brl"])
        else:
            monthly = value / Decimal(12)
            formula = methods[component]["formula_fixed"]
            inputs = {"fixed_annual_brl": {"value": value, "unit": FIXED_UNIT, "nature": "scenario_parameter"}}
            sources = []
        output[component] = {
            "value": _money(monthly), "unit": "BRL/month", "nature": "scenario_estimate",
            "formula": formula, "method_version": VERSION,
            "methodological_origin": methods[component]["methodological_origin"], "reason": None,
            "inputs": inputs, "source_evidence": sources,
        }

    missing = [component for component, evidence in output.items() if evidence["value"] is None]
    total = None if missing else _money(sum((evidence["value"] for evidence in output.values()), Decimal(0)))
    return {
        "contract_version": VERSION, "scenario": scenario_name,
        "components": output, "missing_components": missing,
        "scenario_tco_complete": not missing, "scenario_monthly_tco_brl": total,
        "scenario_total": {
            "value": total, "unit": "BRL/month",
            "nature": "scenario_estimate" if total is not None else "unavailable",
            "formula": "sum(fuel, ipva, maintenance, insurance, depreciation)" if total is not None else None,
            "method_version": VERSION,
            "reason": None if total is not None else "Missing components: " + ", ".join(missing),
        },
        "observed_value_claimed": False,
        "operational_activation_allowed": False,
    }


def _operational_costs(vehicle):
    scenario = deepcopy(profile_configuration()["scenario"])
    scenario["fuel_price_mode"] = "anp"
    return cost_evidence(vehicle, scenario)


def _academic_profile_evaluation(vehicle, profile, target_month, profile_row, academic_costs, config):
    """Project explicitly authorized scenario evidence onto academic gates only."""
    method = profile_configuration()
    definition = method["profiles"][profile]
    values = dict(profile_row["criteria_values"])
    natures = {
        criterion: "operational_method" if value is not None else "unavailable"
        for criterion, value in values.items()
    }
    overrides = {}
    override = config["academic_profile_criterion_overrides"].get(profile, {}).get("operating_cost")
    if override and academic_costs["scenario_tco_complete"]:
        values["operating_cost"] = academic_costs["scenario_monthly_tco_brl"]
        natures["operating_cost"] = override["nature"]
        overrides["operating_cost"] = {
            **override,
            "value": academic_costs["scenario_monthly_tco_brl"],
            "method_version": VERSION,
            "operational_gate_used": False,
        }
    weights = profile_row["original_weights"]
    total_weight = sum(weights.values(), Decimal(0))
    present = [key for key in weights if values[key] is not None]
    temporal_ok = vehicle.fields["reference_month"].value == target_month
    used = [key for key in present if weights[key] > 0] if temporal_ok else []
    denominator = sum((weights[key] for key in used), Decimal(0))
    effective = dict.fromkeys(weights, Decimal(0))
    if denominator:
        for key in used[:-1]:
            effective[key] = (weights[key] / denominator).quantize(
                Decimal(method["precision"]["weight"]), rounding=ROUND_HALF_UP,
            )
        effective[used[-1]] = Decimal(1) - sum(effective.values(), Decimal(0))
    utilities = dict.fromkeys(weights)
    contributions = dict.fromkeys(weights)
    quantum = Decimal(method["precision"]["score"])
    for key in used:
        raw_utility = values[key] if key in {"safety", "transmission"} else utility(
            values[key], method["scales"][key]
        )
        utilities[key] = raw_utility.quantize(quantum, rounding=ROUND_HALF_UP)
        contributions[key] = (utilities[key] * effective[key]).quantize(
            quantum, rounding=ROUND_HALF_UP,
        )
    score = sum((value for value in contributions.values() if value is not None), Decimal(0)) if used else None
    required_missing = [key for key in definition["required"] if values[key] is None]
    required_any_missing = [
        group for group in definition["required_any"]
        if not any(values[key] is not None for key in group)
    ]
    scoreability_reasons = (
        ["PROFILE_REQUIRED_EVIDENCE_MISSING"]
        if required_missing or required_any_missing else []
    )
    return {
        "criteria_values": {key: values[key] for key in weights},
        "criteria_natures": {key: natures[key] for key in weights},
        "criterion_overrides": overrides,
        "available_criteria": present,
        "missing_criteria": [key for key in weights if values[key] is None],
        "required_missing": required_missing,
        "required_any_missing": required_any_missing,
        "weighted_coverage": sum((weights[key] for key in present), Decimal(0)) / total_weight,
        "effective_weights": effective,
        "utilities": utilities,
        "contributions": contributions,
        "preview_score": score,
        "profile_scoreable": not scoreability_reasons,
        "scoreability_reasons": scoreability_reasons,
    }


def evaluate_vehicle(vehicle, profile, scenario_name, target_month, *, config=None):
    config = configuration() if config is None else validate_configuration(deepcopy(config))
    academic_costs = scenario_cost_evidence(vehicle, scenario_name, config=config)
    operational_costs = _operational_costs(vehicle)
    scoring_scenario = deepcopy(profile_configuration()["scenario"])
    scoring_scenario["monthly_km"] = config["common_inputs"]["monthly_km"]["value"]
    scoring_scenario["gasoline_brl_per_l"] = config["common_inputs"]["fuel_price_brl_per_l"]["value"]
    scoring_scenario["fuel_price_mode"] = "manual"
    scoring_scenario["annual_estimate_rates"] = {}
    profile_row = score_vehicle(vehicle, profile, target_month, scenario=scoring_scenario)
    body_footprint = body_footprint_evidence(vehicle, config=config)
    academic_profile = _academic_profile_evaluation(
        vehicle, profile, target_month, profile_row, academic_costs, config,
    )
    academic_ready = bool(
        profile_row["identity_resolved"] and academic_profile["profile_scoreable"]
        and profile_row["profile_eligible"] and academic_costs["scenario_tco_complete"]
    )
    blockers = []
    if not profile_row["identity_resolved"]:
        blockers.append("EXACT_IDENTITY_NOT_RESOLVED")
    blockers.extend(academic_profile["scoreability_reasons"])
    blockers.extend(profile_row["eligibility_reasons"])
    if not academic_costs["scenario_tco_complete"]:
        blockers.append("ACADEMIC_SCENARIO_TCO_INCOMPLETE")
    confidence = {
        "value": None,
        "status": "descriptive_traceability_only_not_statistical_confidence",
        "traceable": profile_row["confidence"]["traceable"],
        "weighted_coverage": academic_profile["weighted_coverage"],
        "presented": True,
    }
    return {
        "id": vehicle.id, "vehicle": vehicle.label, "profile": profile,
        "profile_label": profile_row["profile_label"], "scenario": scenario_name,
        "identity_resolved": profile_row["identity_resolved"],
        "partial_coverage_candidate": profile_row["partial_coverage_candidate"],
        "profile_scoreable": profile_row["profile_scoreable"],
        "academic_profile_scoreable": academic_profile["profile_scoreable"],
        "profile_eligible": profile_row["profile_eligible"],
        "methodology_ready": profile_row["methodology_ready"],
        "observed_tco_complete": operational_costs["is_complete_tco"],
        "observed_monthly_tco_brl": operational_costs["monthly_tco"],
        "scenario_tco_complete": academic_costs["scenario_tco_complete"],
        "scenario_monthly_tco_brl": academic_costs["scenario_monthly_tco_brl"],
        "academic_test_ready": academic_ready,
        "operationally_active": profile_row["operationally_active"],
        "recommended": False,
        "recommendation_ranking_executed": False,
        "academic_preview_score": academic_profile["preview_score"],
        "coverage": {
            "weighted": profile_row["weighted_coverage"],
            "available_criteria": profile_row["available_criteria"],
            "missing_criteria": profile_row["missing_criteria"],
            "required_missing": profile_row["required_missing"],
            "required_any_missing": profile_row["required_any_missing"],
            "presented": True,
        },
        "academic_coverage": {
            "weighted": academic_profile["weighted_coverage"],
            "available_criteria": academic_profile["available_criteria"],
            "missing_criteria": academic_profile["missing_criteria"],
            "required_missing": academic_profile["required_missing"],
            "required_any_missing": academic_profile["required_any_missing"],
            "presented": True,
        },
        "confidence": confidence,
        "blockers": list(dict.fromkeys(blockers)),
        "operational_method_blockers": profile_row["scoreability_reasons"],
        "academic_criteria_values": academic_profile["criteria_values"],
        "academic_criteria_natures": academic_profile["criteria_natures"],
        "academic_criterion_overrides": academic_profile["criterion_overrides"],
        "academic_derived_evidence": {"body_footprint_m2": body_footprint},
        "academic_costs": academic_costs,
        "observed_costs": operational_costs,
    }


def _ties(rows, key):
    groups = {}
    for row in rows:
        value = row[key]
        if value is not None:
            groups.setdefault(value, []).append(row["id"])
    return [{"value": value, "ids": sorted(ids)} for value, ids in groups.items() if len(ids) > 1]


def _price_only_reversals(rows, vehicles_by_id):
    reversals = []
    ready = [row for row in rows if row["scenario_tco_complete"]]
    for index, left in enumerate(ready):
        for right in ready[index + 1:]:
            left_price = vehicles_by_id[left["id"]].fields["price_brl"].value
            right_price = vehicles_by_id[right["id"]].fields["price_brl"].value
            left_fuel = left["academic_costs"]["components"]["fuel"]["value"]
            right_fuel = right["academic_costs"]["components"]["fuel"]["value"]
            left_total, right_total = left["scenario_monthly_tco_brl"], right["scenario_monthly_tco_brl"]
            if (left_price < right_price and left_fuel > right_fuel and left_total < right_total):
                reversals.append({"lower_price_id": left["id"], "higher_price_id": right["id"]})
            elif (right_price < left_price and right_fuel > left_fuel and right_total < left_total):
                reversals.append({"lower_price_id": right["id"], "higher_price_id": left["id"]})
    return reversals


def evaluate_cohort(vehicles, target_month, *, config=None):
    vehicles = tuple(vehicles)
    config = configuration() if config is None else validate_configuration(deepcopy(config))
    if len({vehicle.id for vehicle in vehicles}) != len(vehicles):
        raise ValueError("Duplicate vehicle ID in academic cohort")
    profiles = tuple(profile_configuration()["profiles"])
    by_id = {vehicle.id: vehicle for vehicle in vehicles}
    scenario_reports = {}
    for scenario_name in config["scenarios"]:
        profile_reports = {}
        for profile in profiles:
            rows = [evaluate_vehicle(vehicle, profile, scenario_name, target_month, config=config) for vehicle in vehicles]
            academic_ready = [row for row in rows if row["academic_test_ready"]]
            score_order = [row["id"] for row in sorted(
                (row for row in academic_ready if row["academic_preview_score"] is not None),
                key=lambda row: (-row["academic_preview_score"], row["id"]),
            )]
            tco_order = [row["id"] for row in sorted(
                academic_ready, key=lambda row: (row["scenario_monthly_tco_brl"], row["id"]),
            )]
            thresholds = {
                threshold: [row["id"] for row in rows if row["academic_coverage"]["weighted"] >= Decimal(threshold)]
                for threshold in config["coverage_sensitivity_thresholds"]
            }
            profile_reports[profile] = {
                "profile_label": rows[0]["profile_label"] if rows else profile,
                "rows": rows,
                "counts": {
                    key: sum(bool(row[key]) for row in rows)
                    for key in ("identity_resolved", "partial_coverage_candidate", "profile_scoreable",
                                "academic_profile_scoreable",
                                "profile_eligible", "methodology_ready", "observed_tco_complete",
                                "scenario_tco_complete", "academic_test_ready", "operationally_active", "recommended")
                },
                "academic_preview_score_order": score_order,
                "scenario_tco_order": tco_order,
                "score_ties": _ties(academic_ready, "academic_preview_score"),
                "tco_ties": _ties(academic_ready, "scenario_monthly_tco_brl"),
                "coverage_threshold_diagnostic_ids": thresholds,
                "coverage_thresholds_do_not_promote_readiness": True,
                "price_only_reversals": _price_only_reversals(academic_ready, by_id),
                "recommendation_ranking": [], "recommendation_executed": False,
            }
        scenario_reports[scenario_name] = profile_reports
    sensitivity = {}
    for profile in profiles:
        score_orders = {name: scenario_reports[name][profile]["academic_preview_score_order"] for name in config["scenarios"]}
        tco_orders = {name: scenario_reports[name][profile]["scenario_tco_order"] for name in config["scenarios"]}
        sensitivity[profile] = {
            "academic_preview_score_orders": score_orders,
            "scenario_tco_orders": tco_orders,
            "score_order_changes": len({tuple(order) for order in score_orders.values()}) > 1,
            "tco_order_changes": len({tuple(order) for order in tco_orders.values()}) > 1,
        }
    all_complete_cost_rows = {
        scenario_name: [
            row for row in scenario_reports[scenario_name][profiles[0]]["rows"]
            if row["scenario_tco_complete"]
        ]
        for scenario_name in config["scenarios"]
    }
    complete_tco_orders = {
        scenario_name: [row["id"] for row in sorted(
            rows, key=lambda row: (row["scenario_monthly_tco_brl"], row["id"]),
        )]
        for scenario_name, rows in all_complete_cost_rows.items()
    }
    return {
        "contract_version": VERSION, "target_month": target_month,
        "vehicle_count": len(vehicles), "scenarios": scenario_reports,
        "sensitivity": sensitivity,
        "cost_sensitivity_all_scenario_complete_vehicles": {
            "scenario_tco_orders": complete_tco_orders,
            "order_changes": len({tuple(order) for order in complete_tco_orders.values()}) > 1,
            "positions": {
                scenario_name: {identifier: index + 1 for index, identifier in enumerate(order)}
                for scenario_name, order in complete_tco_orders.items()
            },
            "ties": {
                scenario_name: _ties(rows, "scenario_monthly_tco_brl")
                for scenario_name, rows in all_complete_cost_rows.items()
            },
            "price_only_reversals": {
                scenario_name: _price_only_reversals(rows, by_id)
                for scenario_name, rows in all_complete_cost_rows.items()
            },
            "is_cost_sensitivity_not_recommendation": True,
        },
        "operational_publication_authorized": False,
        "operational_activation_authorized": False,
        "recommendation_ranking_executed": False,
        "preview_only": True,
    }
