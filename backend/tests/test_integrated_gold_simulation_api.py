from dataclasses import replace
from datetime import date
from decimal import Decimal
import inspect

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrated_gold.simulation_repository import VehicleCostSimulationRepository
from app.integrated_gold.simulation_service import VehicleCostSimulationService
from data_platform.contracts.integrated_vehicle_cost import FuelScenarioCode
from data_platform.integrated_vehicle_cost.simulation_contracts import (
    SimulationSourceVersions,
    VehicleCostEvidence,
)


WEEK_START = date(2026, 8, 3)


def evidence():
    return VehicleCostEvidence(
        sources=SimulationSourceVersions(
            integrated_dataset_version="integrated-v1",
            fipe_dataset_version="fipe-v1",
            pbev_dataset_version="pbev-v1",
            anp_dataset_version="anp-v1",
        ),
        vehicle_sk=42,
        brand_name="Volkswagen",
        model_name="Polo",
        version_name="Comfortline",
        model_year=2024,
        fuel_code=FuelScenarioCode.GASOLINE_C_COMMON,
        requested_geography_level="state",
        requested_geography_key="SP",
        anp_week_start=WEEK_START,
        anp_week_end=date(2026, 8, 9),
        city_consumption_km_l=Decimal("12.0000"),
        highway_consumption_km_l=Decimal("15.0000"),
        fuel_price_per_liter_brl=Decimal("6.0000"),
        analytical_scenario_code="mixed_1000_v1",
        analytical_monthly_distance_km=Decimal("1000.00"),
        analytical_annual_distance_km=Decimal("12000.00"),
        analytical_projected_monthly_cost_brl=Decimal("450.0000"),
        analytical_projected_annual_cost_brl=Decimal("5400.0000"),
    )


class FakeSimulationRepository:
    def __init__(self, *, active=True, rows=None):
        self.active = active
        self.rows = tuple(rows) if rows is not None else (evidence(),)
        self.requests = []

    def eligible_dataset(self):
        return {"dataset_version": "integrated-v1"} if self.active else None

    def evidence_rows(self, dataset_version, vehicle_sks):
        self.requests.append((dataset_version, vehicle_sks))
        return self.rows

    def published_exclusions(self, dataset_version, vehicle_sks):
        self.requests.append((dataset_version, vehicle_sks))
        return ()


def client_for(repository):
    from app.integrated_gold.routes import (
        get_vehicle_cost_simulation_service,
        router,
    )

    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_vehicle_cost_simulation_service] = lambda: (
        VehicleCostSimulationService(repository)
    )
    return TestClient(application)


def payload(**changes):
    values = {
        "monthly_distance_km": "1000.00",
        "city_percentage": "50.00",
        "highway_percentage": "50.00",
        "state_code": "SP",
        "municipality": None,
        "reference_week_start": "2026-08-03",
        "fuel_strategy": "gasoline_c_common",
        "horizon_months": 12,
        "vehicle_sks": [42],
        "max_results": 10,
    }
    values.update(changes)
    return values


def test_simulation_endpoint_requires_explicit_scenario_and_preserves_decimal_strings():
    repository = FakeSimulationRepository()
    with client_for(repository) as client:
        response = client.post(
            "/api/v1/integrated-vehicle-cost/simulate",
            json=payload(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["scenario"]["monthly_distance_km"] == "1000.00"
    assert body["results"][0]["estimated_monthly_liters"] == "75.0000"
    assert body["results"][0]["estimated_annual_liters"] == "900.0000"
    assert body["results"][0]["monthly_fuel_cost_brl"] == "450.0000"
    assert body["results"][0]["annual_fuel_cost_brl"] == "5400.0000"
    assert body["results"][0]["projected_horizon_cost_brl"] == "5400.0000"
    assert body["results"][0]["canonical_scenario_code"] == "mixed_1000_v1"
    assert body["results"][0]["monthly_cost_difference_brl"] == "0.0000"
    assert body["results"][0]["fuel_price_origin"] == "anp_gold"
    assert body["results"][0]["canonical_comparison_origin"] == "canonical_policy"
    assert body["results"][0]["sources"] == {
        "integrated_dataset_version": "integrated-v1",
        "fipe_dataset_version": "fipe-v1",
        "pbev_dataset_version": "pbev-v1",
        "anp_dataset_version": "anp-v1",
    }
    assert body["is_simulation"] is True
    assert body["simulation_only"] is True
    assert body["active_gold_unchanged"] is True
    assert body["response_timestamp"].endswith("Z")
    assert repository.requests == [
        ("integrated-v1", (42,)),
        ("integrated-v1", (42,)),
    ]


def test_request_rejects_omissions_floats_booleans_nan_and_invalid_percentages():
    invalid = [
        {key: value for key, value in payload().items() if key != "monthly_distance_km"},
        payload(monthly_distance_km=1000.5),
        payload(monthly_distance_km=True),
        payload(monthly_distance_km="NaN"),
        payload(city_percentage=True),
        payload(city_percentage="40.00", highway_percentage="50.00"),
        payload(vehicle_sks=[True]),
        payload(max_results=True),
        payload(horizon_months=0),
        payload(horizon_months=True),
        payload(manual_fuel_price_brl=5.5),
        payload(manual_fuel_price_brl="NaN"),
        payload(monthly_distance_km="100000.01"),
    ]
    with client_for(FakeSimulationRepository()) as client:
        responses = [
            client.post("/api/v1/integrated-vehicle-cost/simulate", json=item)
            for item in invalid
        ]
    assert all(response.status_code == 422 for response in responses)


def test_manual_inputs_are_isolated_between_stateless_requests():
    repository = FakeSimulationRepository()
    with client_for(repository) as client:
        manual = client.post(
            "/api/v1/integrated-vehicle-cost/simulate",
            json=payload(
                monthly_distance_km="2000.00",
                horizon_months=6,
                manual_fuel_price_brl="5.0000",
                city_consumption_km_l="10.0000",
                highway_consumption_km_l="20.0000",
            ),
        )
        official = client.post(
            "/api/v1/integrated-vehicle-cost/simulate",
            json=payload(),
        )
    assert manual.status_code == 200
    assert official.status_code == 200
    manual_result = manual.json()["results"][0]
    official_result = official.json()["results"][0]
    assert manual_result["fuel_price_origin"] == "user_input"
    assert manual_result["projected_horizon_cost_brl"] != (
        official_result["projected_horizon_cost_brl"]
    )
    assert official_result["fuel_price_origin"] == "anp_gold"


def test_absent_active_dataset_returns_sanitized_error_without_storage_details():
    with client_for(FakeSimulationRepository(active=False)) as client:
        response = client.post(
            "/api/v1/integrated-vehicle-cost/simulate",
            json=payload(),
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "vehicle_cost_simulation_unavailable"
    normalized = response.text.casefold()
    assert "sql" not in normalized
    assert "postgres" not in normalized
    assert "connection" not in normalized


def test_ambiguous_manual_selection_returns_sanitized_conflict():
    repository = FakeSimulationRepository(
        rows=(
            evidence(),
            replace(evidence(), requested_geography_key="RJ"),
        )
    )
    with client_for(repository) as client:
        response = client.post(
            "/api/v1/integrated-vehicle-cost/simulate",
            json=payload(manual_fuel_price_brl="5.0000"),
        )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "vehicle_cost_simulation_selection_conflict",
        "message": "simulation selection matches multiple eligible Gold evidences",
    }
    normalized = response.text.casefold()
    assert "sql" not in normalized
    assert "postgres" not in normalized


def test_repository_and_service_are_read_only_gold_consumers_without_side_effects():
    repository_source = inspect.getsource(VehicleCostSimulationRepository).casefold()
    service_source = inspect.getsource(VehicleCostSimulationService).casefold()
    assert "gold.integrated_vehicle_cost_consumption_v1" in repository_source
    assert "gold.integrated_vehicle_cost_exclusion" in repository_source
    assert " bronze." not in repository_source
    assert " silver." not in repository_source
    for mutation in (
        "insert into",
        "update ",
        "delete from",
        "truncate",
        ".commit(",
        ".rollback(",
    ):
        assert mutation not in repository_source
    combined = repository_source + service_source
    assert "requests." not in combined
    assert "httpx" not in combined
    assert "run_integrated_vehicle_cost_pipeline" not in combined
    assert "acquire_lock" not in combined
