from datetime import UTC, date, datetime
from decimal import Decimal
import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.integrated_gold.repository import IntegratedGoldFilters, IntegratedGoldRepository
from app.integrated_gold.schemas import IntegratedCostItem
from app.integrated_gold.service import IntegratedGoldService


def _dataset():
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return {
        "dataset_version": "integrated-test-v1",
        "fipe_source_dataset_version": "fipe-v1",
        "pbev_source_dataset_version": "pbev-v1",
        "anp_source_dataset_version": "anp-v1",
        "analytic_cutoff_at": now,
        "calculation_policy_version": "integrated-cost-v1",
        "geography_policy_version": "exact-v1",
        "scenario_policy_version": "mixed-v1",
        "quality_policy_version": "integrated-quality-v1",
        "published_vehicle_count": 1,
        "published_scenario_count": 2,
        "catalog_coverage_pct": Decimal("52.94"),
        "pbev_coverage_pct": Decimal("100.00"),
        "first_published_at": now,
        "last_activated_at": now,
    }


def _row(fuel="gasoline_c_common"):
    return {
        "dataset_version": "integrated-test-v1",
        "vehicle_sk": 42,
        "brand_name": "Volkswagen",
        "model_name": "Polo",
        "version_name": "Comfortline 1.0",
        "model_year": 2024,
        "fuel_scenario_code": fuel,
        "requested_geography_level": "state",
        "requested_geography_key": "SP",
        "anp_week_start": date(2026, 8, 3),
        "anp_week_end": date(2026, 8, 9),
        "vehicle_price_brl": Decimal("95000.00"),
        "city_consumption_km_l": Decimal("12.0000"),
        "highway_consumption_km_l": Decimal("14.0000"),
        "fuel_price_per_liter_brl": Decimal("6.1234"),
        "city_cost_per_km_brl": Decimal("0.51028333"),
        "highway_cost_per_km_brl": Decimal("0.43738571"),
        "mixed_cost_per_km_brl": Decimal("0.47383452"),
        "city_distance_share": Decimal("0.5000"),
        "highway_distance_share": Decimal("0.5000"),
        "analytical_scenario_code": "mixed_1000_v1",
        "analytical_monthly_distance_km": Decimal("1000.00"),
        "analytical_annual_distance_km": Decimal("12000.00"),
        "analytical_projected_monthly_cost_brl": Decimal("473.8345"),
        "analytical_projected_annual_cost_brl": Decimal("5686.0140"),
    }


class FakeRepository:
    def __init__(self, *, dataset=True, rows=None):
        self.dataset = _dataset() if dataset else None
        self.rows = list(rows if rows is not None else [_row()])
        self.last_filters = None

    def eligible_dataset(self):
        return self.dataset

    def list_costs(self, dataset_version, filters, **_kwargs):
        assert dataset_version == "integrated-test-v1"
        self.last_filters = filters
        rows = self.rows
        if filters.vehicle_sk is not None:
            rows = [item for item in rows if item["vehicle_sk"] == filters.vehicle_sk]
        return rows, len(rows)


class FakeSqlResult:
    def __init__(self, *, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar = scalar

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.scalar


class FakeIntegratedGoldSession:
    def __init__(self, *, page_rows, total):
        self.page_rows = list(page_rows)
        self.total = total
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        parameters = dict(parameters or {})
        self.calls.append((sql, parameters))
        if "SELECT DISTINCT" in sql:
            dataset = _dataset()
            dataset["published_vehicle_count"] = 18
            dataset["published_scenario_count"] = 54
            return FakeSqlResult(rows=[dataset])
        if "COUNT(*) OVER()" in sql:
            return FakeSqlResult(rows=self.page_rows)
        if "SELECT COUNT(*)" in sql:
            return FakeSqlResult(scalar=self.total)
        raise AssertionError(f"unexpected SQL: {sql}")


def _client(repository):
    from app.integrated_gold.routes import get_integrated_gold_service, router

    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_integrated_gold_service] = lambda: (
        IntegratedGoldService(repository)
    )
    return TestClient(application)


def test_versioned_read_api_preserves_decimal_and_analytical_baseline_semantics():
    repository = FakeRepository(rows=[_row(), _row("ethanol_hydrated")])
    with _client(repository) as client:
        response = client.get(
            "/api/v1/integrated-vehicle-cost/vehicles",
            params={"brand_name": "Volkswagen", "limit": 10, "offset": 0},
        )
        metadata = client.get("/api/v1/integrated-vehicle-cost/metadata")
        detail = client.get("/api/v1/integrated-vehicle-cost/vehicles/42")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["analytical_baseline_only"] is True
    assert body["items"][0]["mixed_cost_per_km_brl"] == "0.47383452"
    assert repository.last_filters.vehicle_sk == 42
    assert metadata.json()["personalization_requires_explicit_inputs"] is True
    assert detail.status_code == 200
    assert len(detail.json()["scenarios"]) == 2


def test_repository_separates_window_total_from_strict_item_payload():
    raw_row = {**_row(), "total_count": 54}
    session = FakeIntegratedGoldSession(page_rows=[raw_row], total=54)
    repository = IntegratedGoldRepository(session)

    rows, total = repository.list_costs(
        "integrated-test-v1",
        IntegratedGoldFilters(),
        limit=1,
        offset=0,
        sort_by="brand_name",
        sort_direction="asc",
    )

    assert total == 54
    assert len(session.calls) == 1
    assert rows == [_row()]
    assert "total_count" not in rows[0]
    assert IntegratedCostItem.model_validate(rows[0]).vehicle_sk == 42


def test_empty_page_uses_filtered_count_and_preserves_top_level_total():
    session = FakeIntegratedGoldSession(page_rows=[], total=54)
    repository = IntegratedGoldRepository(session)

    with _client(repository) as client:
        response = client.get(
            "/api/v1/integrated-vehicle-cost/vehicles",
            params={"limit": 1, "offset": 54},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 54,
        "limit": 1,
        "offset": 54,
        "dataset_version": "integrated-test-v1",
        "analytical_baseline_only": True,
    }
    assert len(session.calls) == 3
    count_sql, count_parameters = session.calls[-1]
    assert "SELECT COUNT(*)" in count_sql
    assert count_parameters == {"dataset_version": "integrated-test-v1"}


def test_real_repository_boundary_returns_200_without_item_pagination_metadata():
    session = FakeIntegratedGoldSession(
        page_rows=[{**_row(), "total_count": 54}],
        total=54,
    )

    with _client(IntegratedGoldRepository(session)) as client:
        response = client.get(
            "/api/v1/integrated-vehicle-cost/vehicles",
            params={"limit": 1},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 54
    assert len(body["items"]) == 1
    assert "total_count" not in body["items"][0]


def test_integrated_cost_item_remains_strict_about_pagination_metadata():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        IntegratedCostItem.model_validate({**_row(), "total_count": 54})


def test_absent_eligible_dataset_returns_stable_sanitized_error():
    with _client(FakeRepository(dataset=False)) as client:
        response = client.get("/api/v1/integrated-vehicle-cost/metadata")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "integrated_gold_unavailable"
    assert "postgres" not in response.text.casefold()


def test_vehicle_filters_pagination_and_sort_contract_are_defensive():
    repository = FakeRepository()
    with _client(repository) as client:
        invalid_limit = client.get(
            "/api/v1/integrated-vehicle-cost/vehicles?limit=101"
        )
        invalid_sort = client.get(
            "/api/v1/integrated-vehicle-cost/vehicles?sort_by=raw_sql"
        )
        missing = client.get("/api/v1/integrated-vehicle-cost/vehicles/999")
    assert invalid_limit.status_code == 422
    assert invalid_sort.status_code == 422
    assert missing.status_code == 404


def test_repository_reads_only_active_eligible_gold_without_mutation_or_lower_layers():
    source = inspect.getsource(IntegratedGoldRepository)
    normalized = source.casefold()
    assert "gold.integrated_vehicle_cost_consumption_v1" in normalized
    assert "integrated_vehicle_cost_dataset" not in normalized
    assert "integrated_vehicle_cost_snapshot" not in normalized
    assert "vehicle_features_snapshot" not in normalized
    assert " bronze." not in normalized
    assert " silver." not in normalized
    assert " legacy" not in normalized
    for mutation in ("insert into", "update ", "delete from", "truncate"):
        assert mutation not in normalized


def test_service_does_not_invent_personalization_inputs():
    metadata = IntegratedGoldService(FakeRepository()).metadata()
    assert metadata.analytical_baseline_scenario == "mixed_1000_v1"
    assert metadata.personalization_requires_explicit_inputs is True
    assert not hasattr(metadata, "customer_monthly_distance_km")
    assert isinstance(IntegratedGoldFilters(), IntegratedGoldFilters)
