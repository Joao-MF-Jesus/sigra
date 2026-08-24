from __future__ import annotations

import ast
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
import inspect
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from data_platform.contracts.integrated_vehicle_cost import (
    CoverageRegressionStatus,
    FuelScenarioCode,
)
from data_platform.integrated_vehicle_cost.cli import main
from data_platform.integrated_vehicle_cost.loader import IntegratedVehicleCostLoader
from data_platform.integrated_vehicle_cost.pipeline import (
    ActiveGoldSources,
    GoldFuelPriceInput,
    GoldVehicleInput,
    IntegratedPublicationError,
    IntegratedPublicationRequest,
    IntegratedVehicleCostOptions,
    build_materialization_plan,
    rollback_integrated_vehicle_cost,
    run_integrated_vehicle_cost_pipeline,
)


def _sources(*, anp_fingerprint: str = "c" * 64) -> ActiveGoldSources:
    return ActiveGoldSources(
        fipe_dataset_version="fipe-v1",
        fipe_fingerprint="a" * 64,
        pbev_dataset_version="pbev-v1",
        pbev_fingerprint="b" * 64,
        anp_dataset_version="anp-v1",
        anp_fingerprint=anp_fingerprint,
    )


def _request() -> IntegratedPublicationRequest:
    return IntegratedPublicationRequest(
        geography_level="municipality",
        geography_key="sao-paulo-sp",
        week_start=date(2026, 8, 3),
    )


def _vehicles() -> tuple[GoldVehicleInput, ...]:
    published_at = datetime(2026, 8, 10, tzinfo=UTC)
    return (
        GoldVehicleInput(
            vehicle_sk=1,
            fipe_gold_record_id=101,
            vehicle_price_brl=Decimal("80000.00"),
            price_reference_month=date(2026, 8, 1),
            fipe_published_at=published_at,
            fipe_currency="BRL",
            pbev_gold_record_id=201,
            pbev_cycle_year=2022,
            fossil_city_km_l=Decimal("10.0000"),
            fossil_highway_km_l=Decimal("15.0000"),
            ethanol_city_km_l=Decimal("7.0000"),
            ethanol_highway_km_l=Decimal("10.0000"),
            pbev_published_at=published_at,
        ),
        GoldVehicleInput(
            vehicle_sk=2,
            fipe_gold_record_id=102,
            vehicle_price_brl=Decimal("90000.00"),
            price_reference_month=date(2026, 8, 1),
            fipe_published_at=published_at,
            fipe_currency="BRL",
            pbev_gold_record_id=None,
            pbev_cycle_year=None,
            fossil_city_km_l=None,
            fossil_highway_km_l=None,
            ethanol_city_km_l=None,
            ethanol_highway_km_l=None,
            pbev_published_at=None,
        ),
    )


def _prices(*, gasoline: str = "6.0000") -> tuple[GoldFuelPriceInput, ...]:
    values = (
        (301, FuelScenarioCode.GASOLINE_C_COMMON, Decimal(gasoline)),
        (302, FuelScenarioCode.GASOLINE_C_ADDITIZED, Decimal("6.2000")),
        (303, FuelScenarioCode.ETHANOL_HYDRATED, Decimal("4.0000")),
    )
    return tuple(
        GoldFuelPriceInput(
            anp_gold_snapshot_id=snapshot_id,
            product_code=product,
            week_start=date(2026, 8, 3),
            week_end=date(2026, 8, 9),
            geography_level="municipality",
            geography_key="sao-paulo-sp",
            median_price=price,
            currency_code="BRL",
            unit_code="liter",
        )
        for snapshot_id, product, price in values
    )


def _plan(**kwargs):
    return build_materialization_plan(
        sources=kwargs.pop("sources", _sources()),
        request=kwargs.pop("request", _request()),
        vehicles=kwargs.pop("vehicles", _vehicles()),
        fuel_prices=kwargs.pop("fuel_prices", _prices()),
        analytic_cutoff_at=datetime(2026, 8, 11, tzinfo=UTC),
        **kwargs,
    )


def test_materialization_uses_decimal_gold_lineage_and_auditable_exclusion():
    plan = _plan()
    assert plan.catalog_universe_count == 2
    assert plan.pbev_matched_universe_count == 1
    assert plan.published_vehicle_count == 1
    assert plan.excluded_vehicle_count == 1
    assert plan.published_scenario_count == 3
    assert plan.catalog_coverage_pct == Decimal("50.00")
    assert plan.pbev_coverage_pct == Decimal("100.00")
    assert {item.fuel_scenario_code for item in plan.snapshots} == set(
        FuelScenarioCode
    )
    assert plan.exclusions[0].reason_code == "PBEV_MATCHED_GOLD_NOT_AVAILABLE"
    assert len(plan.flex_comparisons) == 1
    assert all(
        isinstance(item.projected_monthly_cost_brl, Decimal)
        for item in plan.snapshots
    )


def test_fingerprint_is_deterministic_and_material_changes_create_new_identity():
    first = _plan()
    reordered = _plan(
        vehicles=tuple(reversed(_vehicles())),
        fuel_prices=tuple(reversed(_prices())),
    )
    changed = _plan(
        sources=_sources(anp_fingerprint="d" * 64),
        fuel_prices=_prices(gasoline="6.1000"),
    )
    assert first.dataset_fingerprint == reordered.dataset_fingerprint
    assert first.dataset_fingerprint != changed.dataset_fingerprint


def test_required_products_and_exact_geography_are_hard_failures():
    with pytest.raises(IntegratedPublicationError, match="required fuel product"):
        _plan(
            fuel_prices=tuple(
                item
                for item in _prices()
                if item.product_code is not FuelScenarioCode.ETHANOL_HYDRATED
            )
        )
    wrong = GoldFuelPriceInput(
        **{
            **_prices()[0].__dict__,
            "geography_key": "other-city",
        }
    )
    with pytest.raises(IntegratedPublicationError, match="exact request grain"):
        _plan(fuel_prices=(wrong, *_prices()[1:]))


def test_quality_evidence_has_29_hard_gates_and_seven_uncalibrated_controls():
    plan = _plan()
    assert len(plan.quality_results) == 36
    assert sum(item.rule_kind == "hard_gate" for item in plan.quality_results) == 29
    assert sum(item.status == "not_calibrated" for item in plan.quality_results) == 7
    assert all(
        item.status == "passed"
        for item in plan.quality_results
        if item.rule_kind == "hard_gate"
    )


def test_coverage_regression_is_persistable_but_not_activatable():
    plan = _plan(
        baseline_event_id=7,
        baseline_catalog_coverage_pct=Decimal("60.00"),
        baseline_pbev_coverage_pct=Decimal("100.00"),
    )
    assert plan.coverage_regression_status is CoverageRegressionStatus.MANUAL_REVIEW_REQUIRED
    assert not plan.activation_authorized
    regression = next(
        item
        for item in plan.quality_results
        if item.rule_code == "INTEGRATED_COVERAGE_NON_REGRESSION"
    )
    assert regression.status == "failed"


class FakeLoader:
    is_postgresql = True

    def __init__(self):
        self.sources = _sources()
        self.vehicles = _vehicles()
        self.fuel_prices = _prices()
        self.baseline = None
        self.datasets: dict[str, dict[str, object]] = {}
        self.persisted: list[tuple[str, str | None, str | None]] = []
        self.activation_events: list[tuple[str, str, str | None]] = []
        self.rollbacks = 0
        self.fail_persistence = False

    @contextmanager
    def publication_transaction(self):
        try:
            yield object()
        except BaseException:
            self.rollbacks += 1
            raise

    def load_active_sources(self, _connection):
        return self.sources

    def load_vehicle_inputs(self, _connection, _sources):
        return self.vehicles

    def load_fuel_prices(self, _connection, _sources, _request):
        return self.fuel_prices

    def load_current_baseline(self, _connection):
        return self.baseline

    def transaction_timestamp(self, _connection):
        return datetime(2026, 8, 11, tzinfo=UTC)

    def find_dataset_by_fingerprint(self, _connection, fingerprint):
        return next(
            (item for item in self.datasets.values() if item["dataset_fingerprint"] == fingerprint),
            None,
        )

    def find_dataset_by_version(self, _connection, dataset_version):
        return self.datasets.get(dataset_version)

    def find_active_dataset(self, _connection):
        return next(
            (item for item in self.datasets.values() if item["is_active_shadow"]),
            None,
        )

    def get_dataset(self, _connection, dataset_version):
        return self.datasets.get(dataset_version)

    def start_run(self, _connection, **_kwargs):
        return None

    def finish_run(self, _connection, **_kwargs):
        return None

    def persist_materialization(
        self,
        _connection,
        *,
        dataset_version,
        plan,
        activation_type,
        previous_dataset_version,
        **_kwargs,
    ):
        if self.fail_persistence:
            raise RuntimeError("synthetic persistence failure")
        if previous_dataset_version is not None and activation_type is not None:
            self.datasets[previous_dataset_version]["is_active_shadow"] = False
            self.datasets[previous_dataset_version]["status"] = "retired"
        active = activation_type is not None
        self.datasets[dataset_version] = {
            "dataset_version": dataset_version,
            "dataset_fingerprint": plan.dataset_fingerprint,
            "is_active_shadow": active,
            "status": "shadow_published" if active else "building",
            "quality_status": "passed" if active else "failed",
            "hard_gate_status": "passed" if active else "failed",
            "coverage_regression_status": plan.coverage_regression_status.value,
            "is_invalidated": False,
            "published_vehicle_count": plan.published_vehicle_count,
            "excluded_vehicle_count": plan.excluded_vehicle_count,
            "published_scenario_count": plan.published_scenario_count,
            "catalog_coverage_pct": plan.catalog_coverage_pct,
            "pbev_coverage_pct": plan.pbev_coverage_pct,
        }
        self.persisted.append(
            (dataset_version, activation_type, previous_dataset_version)
        )
        if activation_type is not None:
            self.activation_events.append(
                (activation_type, dataset_version, previous_dataset_version)
            )

    def activate_rollback(
        self,
        _connection,
        *,
        dataset_version,
        previous_dataset_version,
        **_kwargs,
    ):
        self.datasets[previous_dataset_version]["is_active_shadow"] = False
        self.datasets[previous_dataset_version]["status"] = "retired"
        self.datasets[dataset_version]["is_active_shadow"] = True
        self.datasets[dataset_version]["status"] = "shadow_published"
        self.activation_events.append(
            ("rollback", dataset_version, previous_dataset_version)
        )


def _options() -> IntegratedVehicleCostOptions:
    return IntegratedVehicleCostOptions(request=_request())


def test_initial_publication_deduplication_and_supersession():
    loader = FakeLoader()
    initial = run_integrated_vehicle_cost_pipeline(loader, _options())
    duplicate = run_integrated_vehicle_cost_pipeline(loader, _options())
    assert initial.status == "succeeded"
    assert initial.activation_type == "publish"
    assert duplicate.status == "deduplicated"
    assert duplicate.dataset_version == initial.dataset_version
    assert len(loader.persisted) == 1
    assert len(loader.activation_events) == 1

    loader.sources = _sources(anp_fingerprint="d" * 64)
    loader.fuel_prices = _prices(gasoline="6.1000")
    replacement = run_integrated_vehicle_cost_pipeline(loader, _options())
    assert replacement.status == "succeeded"
    assert replacement.activation_type == "replace"
    assert replacement.previous_dataset_version == initial.dataset_version
    assert len(loader.persisted) == 2
    assert len(loader.activation_events) == 2


def test_failure_rolls_back_the_atomic_publication_unit():
    loader = FakeLoader()
    loader.fail_persistence = True
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        run_integrated_vehicle_cost_pipeline(loader, _options())
    assert loader.datasets == {}
    assert loader.activation_events == []
    assert loader.rollbacks == 1


def test_regression_preserves_evidence_without_activation():
    loader = FakeLoader()
    loader.baseline = {
        "baseline_event_id": 5,
        "catalog_coverage_pct": Decimal("60.00"),
        "pbev_coverage_pct": Decimal("100.00"),
    }
    result = run_integrated_vehicle_cost_pipeline(loader, _options())
    assert result.status == "manual_review_required"
    assert result.activation_type is None
    assert len(loader.persisted) == 1
    assert loader.activation_events == []


def test_retired_dataset_rollback_is_atomic_and_idempotent():
    loader = FakeLoader()
    first = run_integrated_vehicle_cost_pipeline(loader, _options())
    loader.sources = _sources(anp_fingerprint="d" * 64)
    loader.fuel_prices = _prices(gasoline="6.1000")
    second = run_integrated_vehicle_cost_pipeline(loader, _options())
    rollback = rollback_integrated_vehicle_cost(loader, first.dataset_version)
    repeated = rollback_integrated_vehicle_cost(loader, first.dataset_version)
    assert second.dataset_version != first.dataset_version
    assert rollback.status == "succeeded"
    assert rollback.activation_type == "rollback"
    assert rollback.previous_dataset_version == second.dataset_version
    assert repeated.status == "deduplicated"
    assert [item[0] for item in loader.activation_events] == [
        "publish",
        "replace",
        "rollback",
    ]


def test_invalid_or_manual_review_dataset_cannot_be_rolled_back():
    loader = FakeLoader()
    loader.datasets["active"] = {
        "dataset_version": "active",
        "dataset_fingerprint": "a" * 64,
        "is_active_shadow": True,
        "status": "shadow_published",
        "quality_status": "passed",
        "hard_gate_status": "passed",
        "coverage_regression_status": "passed",
        "is_invalidated": False,
        "published_vehicle_count": 1,
        "excluded_vehicle_count": 0,
        "published_scenario_count": 1,
        "catalog_coverage_pct": Decimal("100.00"),
        "pbev_coverage_pct": Decimal("100.00"),
    }
    loader.datasets["blocked"] = {
        **loader.datasets["active"],
        "dataset_version": "blocked",
        "dataset_fingerprint": "b" * 64,
        "is_active_shadow": False,
        "status": "retired",
        "coverage_regression_status": "manual_review_required",
    }
    with pytest.raises(IntegratedPublicationError, match="not eligible"):
        rollback_integrated_vehicle_cost(loader, "blocked")
    assert loader.activation_events == []

    loader.datasets["blocked"]["coverage_regression_status"] = "passed"
    loader.datasets["blocked"]["is_invalidated"] = True
    with pytest.raises(IntegratedPublicationError, match="not eligible"):
        rollback_integrated_vehicle_cost(loader, "blocked")
    assert loader.activation_events == []


def test_dry_run_does_not_require_loader_database_lock_network_or_file(tmp_path):
    before = tuple(tmp_path.iterdir())
    result = run_integrated_vehicle_cost_pipeline(
        None,
        IntegratedVehicleCostOptions(request=_request(), dry_run=True),
    )
    assert result.status == "dry_run"
    assert result.plan["writes"] is False
    assert result.plan["hard_gate_count"] == 29
    assert tuple(tmp_path.iterdir()) == before


def test_cli_dry_run_never_creates_an_engine(monkeypatch, capsys):
    monkeypatch.setattr(
        "data_platform.integrated_vehicle_cost.cli.create_platform_engine",
        lambda _url: (_ for _ in ()).throw(AssertionError("database opened")),
    )
    exit_code = main(
        [
            "dry-run",
            "--geography-level",
            "municipality",
            "--geography-key",
            "sao-paulo-sp",
            "--week-start",
            "2026-08-03",
        ]
    )
    payload = capsys.readouterr().out
    assert exit_code == 0
    assert '"status": "dry_run"' in payload
    assert "database opened" not in payload


def test_cli_failure_is_sanitized_and_returns_nonzero(monkeypatch, capsys):
    def fail_engine(_url):
        raise RuntimeError("token=fixture-secret")

    monkeypatch.setattr(
        "data_platform.integrated_vehicle_cost.cli.create_platform_engine",
        fail_engine,
    )
    exit_code = main(
        [
            "publish",
            "--geography-level",
            "municipality",
            "--geography-key",
            "sao-paulo-sp",
            "--week-start",
            "2026-08-03",
        ]
    )
    payload = capsys.readouterr().out
    assert exit_code == 2
    assert "fixture-secret" not in payload
    assert "token=***" in payload


def test_sqlite_is_a_deliberate_analytical_noop():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        loader = IntegratedVehicleCostLoader(engine)
        result = run_integrated_vehicle_cost_pipeline(loader, _options())
        assert result.status == "skipped"
    finally:
        engine.dispose()


def test_loader_is_gold_only_repeatable_read_and_uses_transaction_lock():
    source = inspect.getsource(IntegratedVehicleCostLoader)
    assert 'isolation_level="REPEATABLE READ"' in source
    assert "pg_advisory_xact_lock" in source
    assert "gold.vehicle_features_snapshot" in source
    assert "gold.vehicle_efficiency_snapshot" in source
    assert "gold.anp_fuel_price_snapshot" in source
    assert "bronze." not in source
    assert "silver." not in source


def test_materialization_financial_code_contains_no_float_literals_or_conversion():
    path = Path("data_platform/integrated_vehicle_cost/pipeline.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    materialization = functions["build_materialization_plan"]
    assert not any(
        isinstance(node, ast.Constant) and isinstance(node.value, float)
        for node in ast.walk(materialization)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
        for node in ast.walk(materialization)
    )
