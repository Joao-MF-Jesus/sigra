"""Cost evidence is not a replacement for the production financial engine."""
from decimal import Decimal, ROUND_HALF_UP

from data_platform.catalog.profile_contracts_v3 import available

COMPONENTS = ("fuel", "maintenance", "ipva", "insurance", "depreciation")


def exact(value):
    if isinstance(value, (bool, float)):
        raise ValueError("Exact Decimal input required")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Finite Decimal input required")
    return result


def validate_scenario(scenario):
    required = {"monthly_km", "gasoline_brl_per_l", "transmission_preference", "annual_estimate_rates"}
    if not required <= set(scenario) or set(scenario)-required-{"fuel_price_mode"}:
        raise ValueError("Explicit scenario fields required")
    km = exact(scenario["monthly_km"])
    price = exact(scenario["gasoline_brl_per_l"])
    if km < 0 or price <= 0:
        raise ValueError("Invalid distance or fuel price")
    if scenario["transmission_preference"] not in {None, "manual", "automatic", "cvt"}:
        raise ValueError("Unsupported transmission preference")
    if scenario.get("fuel_price_mode", "manual") not in {"manual", "anp"}:
        raise ValueError("No silent fuel-price fallback")
    rates = scenario["annual_estimate_rates"]
    if not isinstance(rates, dict) or set(rates)-set(COMPONENTS[1:]):
        raise ValueError("Unsupported annual estimate component")
    if any(not Decimal(0) <= exact(value) <= Decimal(1) for value in rates.values()):
        raise ValueError("Annual simulation rates must be fractions between zero and one")
    return km, price


def cost_evidence(vehicle, scenario):
    km, manual_price = validate_scenario(scenario)
    money = Decimal("0.01")
    def rounded(value):
        return value.quantize(money, rounding=ROUND_HALF_UP) if value is not None else None
    known = dict.fromkeys(COMPONENTS)
    estimates = dict.fromkeys(COMPONENTS)
    derivations = {}
    mode = scenario.get("fuel_price_mode", "manual")
    # PBEV fossil figures here are specifically gasoline. Other fuels cannot
    # use this scenario silently.
    gasoline_compatible = available(vehicle, "fuel") and vehicle.fields["fuel"].value in {"gasoline", "flex"}
    fuel = None
    refs = []
    if gasoline_compatible and available(vehicle, "consumption_city"):
        consumption = vehicle.fields["consumption_city"].value
        if mode == "manual":
            fuel = km / consumption * manual_price
            estimates["fuel"] = rounded(fuel)
            price = manual_price
            basis = "explicit_user_scenario_not_ANP_observation"
        elif available(vehicle, "gasoline_brl_per_l"):
            context = vehicle.provenance.get("anp_context", {})
            # Fail closed on source/time/geography. A bare price is insufficient.
            if not context.get("week_start") or not context.get("geography") or context.get("fuel") != "gasoline":
                raise ValueError("ANP week/geography/fuel provenance required")
            from datetime import date
            date.fromisoformat(context["week_start"])
            price = vehicle.fields["gasoline_brl_per_l"].value
            fuel = km / consumption * price
            known["fuel"] = rounded(fuel)
            refs.extend(vehicle.fields["gasoline_brl_per_l"].sources)
            basis = "derived_from_observed_PBEV_and_ANP_under_user_distance_not_actual_spending"
        else:
            price = None
            basis = "ANP_unavailable_no_manual_fallback"
        refs.extend(vehicle.fields["consumption_city"].sources)
        derivations["fuel"] = {
            "formula": "monthly_km / observed_gasoline_city_km_l * selected_gasoline_brl_per_l",
            "inputs": {"monthly_km": km, "consumption_city_km_l": consumption, "selected_price_brl_per_l": price},
            "basis": basis, "sources": refs,
        }
    for component in COMPONENTS[1:]:
        name = component + "_annual_brl"
        observation = vehicle.fields[name]
        if observation.kind == "observed" and observation.value is not None:
            known[component] = rounded(observation.value / Decimal(12))
            derivations[component] = {"formula": name+" / 12 exactly once", "sources": observation.sources,
                                      "annual_value": observation.value, "status": "observed_input_monthly_conversion"}
        elif component in scenario["annual_estimate_rates"] and available(vehicle, "price_brl"):
            rate = exact(scenario["annual_estimate_rates"][component])
            estimates[component] = rounded(vehicle.fields["price_brl"].value * rate / Decimal(12))
            derivations[component] = {
                "formula": "acquisition_reference_price * explicit_user_annual_rate / 12",
                "annual_rate": rate, "acquisition_reference_price": vehicle.fields["price_brl"].value,
                "status": "user_configured_projection_not_observation",
            }
    missing = [key for key in COMPONENTS if known[key] is None]
    def partial_sum(values):
        retained = [value for value in values if value is not None]
        return sum(retained, Decimal(0)) if retained else None
    known_total = partial_sum(known.values())
    estimated_total = partial_sum(estimates.values())
    return {
        "acquisition_reference_price": vehicle.fields["price_brl"].value,
        "reference_month": vehicle.fields["reference_month"].value,
        "observed_monthly_fuel_cost": known["fuel"],
        "known_monthly_cost": known_total,
        "estimated_monthly_cost": estimated_total,
        "known_components": known,
        "estimated_components": estimates,
        "combined_partial_monthly_cost": partial_sum([known_total, estimated_total]),
        "missing_cost_components": missing,
        "is_complete_tco": not missing,
        "monthly_tco": known_total if not missing else None,
        "monthly_budget_eligible": None,
        "label": "custo mensal parcial" if missing else "TCO no escopo declarado de cinco componentes",
        "unit": "BRL/month", "derivations": derivations,
        "urban_fuel_for_scenario": rounded(fuel),
        "proven_operating_cost": known["fuel"] + known["maintenance"] if known["fuel"] is not None and known["maintenance"] is not None else None,
        "assumptions": {
            **scenario, "fuel_price_mode": mode,
            "fuel_scope": "gasoline urban PBEV lab efficiency; not measured individual expenditure",
            "cost_scope": list(COMPONENTS),
            "excluded_contextual_expenses": ["financing", "parking", "tolls"],
            "annual_estimates_are_not_observed": True,
            "estimated_total_excludes_known_components": True,
            "missing_does_not_mean_zero": True,
        },
    }
