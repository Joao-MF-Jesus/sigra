"""v6 evidence adapter for the unchanged seven-criterion opt-in policy.

No v4 criterion is relabelled as a legacy quality, comfort or safety score.
Missing required evidence leaves final_score null and preserves the baseline.
"""
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

from app.multifactor_recommendation import apply_multifactor_ranking
from data_platform.integrated_vehicle_cost.simulation import _calculate
from data_platform.contracts.integrated_vehicle_cost import FuelScenarioCode
from data_platform.catalog.profile_pilot_v4 import fingerprint
from app.academic_cohort.evidence_diagnostics import personalization_evidence
from app.academic_cohort.seven_criteria import criterion_calculations


def personalized_fuel(vehicle, scenario):
    """Reuse the existing mixed-route Decimal formula without forging Gold IDs."""
    if scenario.manual_fuel_price_brl is None:
        return None, "Não há preço ANP publicado para a UF, município e semana solicitados nesta coorte. Informe o preço por litro."
    if scenario.fuel_strategy.value == "lowest_projected_cost":
        return None, "Falta evidência de preços e consumos para comparar os combustíveis."
    fuel = vehicle.fields["fuel"].value
    requested = scenario.fuel_strategy.value
    if fuel not in ({"flex", "ethanol"} if requested == "ethanol_hydrated" else {"flex", "gasoline"}):
        return None, "O combustível escolhido não corresponde à evidência deste veículo."
    city = scenario.city_consumption_km_l
    highway = scenario.highway_consumption_km_l
    if requested == "gasoline_c_common":
        city = city if city is not None else vehicle.fields["consumption_city"].value
        highway = highway if highway is not None else vehicle.fields["consumption_highway"].value
    # The stored PBEV fields refer to gasoline. Never reinterpret them as ethanol.
    if city is None or highway is None:
        return None, "Consumo urbano ou rodoviário do combustível selecionado não está disponível."
    city, highway = Decimal(str(city)), Decimal(str(highway))
    if city <= 0 or highway <= 0:
        return None, "O consumo precisa ser positivo."
    sources = SimpleNamespace(integrated_dataset_version=None, fipe_dataset_version=None,
                              pbev_dataset_version=None, anp_dataset_version=None)
    evidence = SimpleNamespace(city_consumption_km_l=city, highway_consumption_km_l=highway,
        fuel_price_per_liter_brl=scenario.manual_fuel_price_brl,
        analytical_projected_monthly_cost_brl=Decimal(1),
        analytical_projected_annual_cost_brl=Decimal(12), analytical_monthly_distance_km=Decimal(1000),
        analytical_scenario_code=None, sources=sources,
        vehicle_sk=None, brand_name=vehicle.label, model_name=vehicle.label,
        version_name=vehicle.fields["commercial_identity"].value,
        model_year=int(vehicle.fields["year_code"].value.split("-")[0]),
        fuel_code=FuelScenarioCode(requested), anp_week_start=None, anp_week_end=None)
    result = _calculate(scenario, evidence, single_fuel_for_lowest=False)
    # Only the mathematical calculation is shared. Gold comparison/origin claims
    # from that transport contract do not apply to the academic namespace.
    values = dict(result.__dict__)
    values.update(monthly_cost_difference_brl=None, monthly_cost_difference_percentage=None,
                  canonical_scenario_code=None, warnings=(), limitations=())
    return SimpleNamespace(**values), None


def apply_fuel_to_evaluation(result, simulation, scenario):
    component = result["scenario_costs"]["components"]["fuel"]
    component.update(value=simulation.monthly_fuel_cost_brl, nature="scenario_estimate",
        formula="monthly_distance_km * (city_share / city_km_l + highway_share / highway_km_l) * manual_price",
        method_version=simulation.simulation_policy_version,
        inputs={"scenario": scenario.canonical_payload(),
                "city_consumption_km_l": str(simulation.city_consumption_km_l),
                "highway_consumption_km_l": str(simulation.highway_consumption_km_l)})
    total = sum((Decimal(str(c["value"])) for c in result["scenario_costs"]["components"].values()
                 if c["value"] is not None), Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    result["scenario_monthly_tco_brl"] = total
    result["scenario_costs"]["scenario_monthly_tco_brl"] = total
    result["scenario_costs"]["scenario_total"]["value"] = total
    for key in ("urban_fuel", "operating_cost"):
        if key in result["criteria"]:
            result["criteria"][key].update(value=simulation.monthly_fuel_cost_brl if key == "urban_fuel" else total,
                nature="scenario_estimate", formula=component["formula"] if key == "urban_fuel" else "sum(monthly_components)")


def personalize_groups(groups, profile, simulations, errors, scenario):
    """Same original normalization, missing-evidence rule and tie breakers."""
    for rows in groups.values():
        def resolve(item):
            identifier = item["vehicle"]["catalog_id"]
            return simulations.get(identifier), {
                "match_method": "validated_academic_snapshot_and_exact_fipe",
                "identity_namespace": "academic_v6", "operational_vehicle_id": None,
                "rejection_reason": "scenario_evidence_unavailable" if identifier not in simulations else None,
            }
        batch = SimpleNamespace(results=(), fingerprint=fingerprint({"scenario": scenario.canonical_payload(),
            "computed_evidence": {identifier: {"fuel": str(value.monthly_fuel_cost_brl),
                                               "consumption": str(value.weighted_consumption_km_l)}
                                  for identifier, value in simulations.items()}}))
        # Recovered maintenance/resale subcalculations are scenario estimates.
        # Missing reliability/parts still prevent the original four-input mean.
        # Academic v4 utilities are never substituted for original criteria.
        transformed = apply_multifactor_ranking(rows, batch, profile.weights.as_mapping(), evidence_resolver=resolve)
        for position, row in enumerate(transformed, 1):
            identifier = row["vehicle"]["catalog_id"]
            multifactor = row["multifactor"]
            multifactor["scenario"] = scenario.canonical_payload()
            multifactor["source_namespace"] = "academic_v6"
            multifactor["scenario_applied"] = identifier in simulations
            multifactor["evidence_coverage"] = personalization_evidence(row, simulations.get(identifier), profile.weights.as_mapping())
            if identifier in errors:
                multifactor["user_message"] = errors[identifier]
            elif multifactor["status"] != "ranked":
                missing = [r["label"] for r in multifactor["evidence_coverage"]["criteria"] if r["requested"] and not r["available"]]
                multifactor["user_message"] = "Faltam notas comprovadas de " + ", ".join(missing) + ". A ordem de referência foi preservada."
            if "cost" in multifactor:
                multifactor["cost"]["sources"] = {"namespace": "academic_v6", "price_origin": "user_input", "consumption_origin": "PBEV_or_explicit_user_input"}
            for component in multifactor.get("components", ()):
                if component["component"] == "total_cost":
                    component["source"] = "academic_user_scenario_fuel_projection"
                elif component["component"] == "efficiency":
                    component["source"] = "validated_pbev_or_explicit_user_consumption"
            row["score"] = multifactor["final_score"] if multifactor["status"] == "ranked" else row["baseline_score"]
            row["group_position"] = position
        for row in transformed:
            row["multifactor"]["criterion_calculations"] = criterion_calculations(
                row, transformed, simulations, scenario, profile.weights.as_mapping())
        rows[:] = transformed
