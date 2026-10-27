"""Materializa a Gold integrada em um PostgreSQL local de demonstracao.

Este bootstrap nao chama rede, nao altera schema e nao transforma fixtures
sinteticas em evidencias oficiais. FIPE e reproduzida a partir do cache local
versionado com status ``live``; PBEV e ANP usam fixtures explicitamente marcadas
como ``demo_fixture``. O comando recusa qualquer host nao local ou banco cujo
nome nao seja ``sigra_postgresql_demo``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
for import_root in (PROJECT_ROOT, BACKEND_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

# O runtime oficial carrega os contratos de orquestracao antes do ramo PBEV.
# Preservar essa ordem evita o ciclo runner -> pbev.pipeline -> contracts.
import data_platform.orchestration  # noqa: E402,F401

from app import models  # noqa: E402
from app.sample_data import VEHICLES as SAMPLE_VEHICLES  # noqa: E402
from backend.app.fipe import FIPE_REFERENCE_PROFILES  # noqa: E402
from data_platform.anp.loader import AnpFuelPriceLoader  # noqa: E402
from data_platform.anp.pipeline import (  # noqa: E402
    AnpExecutionOptions,
    run_anp_pipeline,
)
from data_platform.anp.sources import ANP_EXPECTED_HEADER  # noqa: E402
from data_platform.common.logging import sanitize  # noqa: E402
from data_platform.contracts.anp_fuel_prices import DownloadedAnpAsset  # noqa: E402
from data_platform.contracts.fipe import FipeTarget  # noqa: E402
from data_platform.contracts.pbev import (  # noqa: E402
    PBEV_MATCHER_VERSION,
    PBEV_PARSER_VERSION,
    ExternalVehicleIdentity,
    ExternalVehicleMapping,
    MatchMethod,
    MappingStatus,
    ParsedPbevRow,
    PbevAssetParseResult,
    PbevRawRow,
    SourceAsset,
)
from data_platform.ingestion.fipe.client import FipeResponse  # noqa: E402
from data_platform.ingestion.fipe.loader import BronzeLoader  # noqa: E402
from data_platform.ingestion.fipe.pipeline import run_pipeline  # noqa: E402
from data_platform.integrated_vehicle_cost.loader import (  # noqa: E402
    IntegratedVehicleCostLoader,
)
from data_platform.integrated_vehicle_cost.pipeline import (  # noqa: E402
    IntegratedPublicationRequest,
    IntegratedVehicleCostOptions,
    run_integrated_vehicle_cost_pipeline,
)
from data_platform.pbev.loader import PbevLoader  # noqa: E402
from data_platform.pbev.targets import load_current_catalog_targets  # noqa: E402
from data_platform.publication.loader import GoldLoader  # noqa: E402
from data_platform.publication.pipeline import run_gold_publication  # noqa: E402
from data_platform.quality.pbev_checks import (  # noqa: E402
    build_coverage_report,
    enforce_audited_pilot_baseline,
    validate_shadow_rows,
)
from data_platform.transformation.loader import SilverLoader  # noqa: E402
from data_platform.transformation.pipeline import run_silver_pipeline  # noqa: E402


EXPECTED_ALEMBIC_HEAD = "20260811_0012"
EXPECTED_CATALOG_IDS = frozenset(range(1, 35))
DEMO_DATABASE = "sigra_postgresql_demo"
DEMO_PORT = 54329
DEMO_CATALOG_MARKER = "postgresql-demo-catalog-v1"
DEMO_PROVENANCE = "demo_fixture"
FIPE_SOURCE_REFERENCE = "fipe-live-cache-julho-2026-local-replay"
PBEV_SOURCE_REFERENCE = "demo_fixture:pbev:minimal:v1"
ANP_SOURCE_REFERENCE = "demo_fixture:anp:2026-08-03:v1"
PBEV_METHODOLOGY = "SIGRA demo_fixture synthetic cycle; not official PBEV evidence"
DEMO_WEEK_START = date(2026, 8, 3)
DEMO_GEOGRAPHY_LEVEL = "municipality"
DEMO_GEOGRAPHY_KEY = "SP:SAO PAULO"
FIXED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _public_result(result: object) -> dict[str, object]:
    return _json_value(asdict(result))


def validate_demo_database_url(raw_url: str) -> dict[str, object]:
    """Valida o destino sem devolver usuario, senha ou URL."""
    if not raw_url.strip():
        raise ValueError("DATA_PLATFORM_DATABASE_URL is required")
    parsed = make_url(raw_url)
    host = (parsed.host or "").casefold()
    database = (parsed.database or "").casefold()
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("demo bootstrap requires PostgreSQL")
    if host != "127.0.0.1":
        raise ValueError("demo bootstrap requires the authorized 127.0.0.1 host")
    if parsed.port != DEMO_PORT:
        raise ValueError("demo bootstrap requires the authorized local PostgreSQL port")
    if not database.endswith("_demo") or database != DEMO_DATABASE:
        raise ValueError("demo bootstrap requires the authorized _demo database")
    return {
        "backend": "postgresql",
        "host_local": True,
        "port": DEMO_PORT,
        "database": DEMO_DATABASE,
        "database_name_safe": True,
    }


def configured_demo_database_url() -> tuple[str, dict[str, object]]:
    data_platform_url = os.getenv("DATA_PLATFORM_DATABASE_URL", "").strip()
    application_url = os.getenv("DATABASE_URL", "").strip()
    raw_url = data_platform_url or application_url
    summary = validate_demo_database_url(raw_url)
    if data_platform_url and application_url:
        left = make_url(data_platform_url)
        right = make_url(application_url)
        identities = (
            left.get_backend_name(),
            (left.host or "").casefold(),
            left.port,
            (left.database or "").casefold(),
            left.username,
            left.password,
        ), (
            right.get_backend_name(),
            (right.host or "").casefold(),
            right.port,
            (right.database or "").casefold(),
            right.username,
            right.password,
        )
        if identities[0] != identities[1]:
            raise ValueError("DATABASE_URL and DATA_PLATFORM_DATABASE_URL target different databases")
    return raw_url, summary


def _canonical_catalog_rows() -> tuple[dict[str, object], ...]:
    rows = tuple(
        {
            "id": int(vehicle.id),
            "brand": vehicle.brand,
            "model": vehicle.model,
            "year": int(vehicle.year),
            "price": vehicle.price,
            "fuel_efficiency_km_l": vehicle.fuel_efficiency_km_l,
            "annual_maintenance_cost": vehicle.annual_maintenance_cost,
            "reliability_score": vehicle.reliability_score,
            "parts_availability_score": vehicle.parts_availability_score,
            "depreciation_rate": vehicle.depreciation_rate,
            "use_cases": "|".join(vehicle.use_cases),
            "chronic_issues": "|".join(vehicle.chronic_issues),
            "image_url": vehicle.image_url,
            "category": vehicle.category,
            "segment_level": vehicle.segment_level,
            "comfort_score": vehicle.comfort_score,
            "space_score": vehicle.space_score,
            "safety_score": vehicle.safety_score,
            "urban_score": vehicle.urban_score,
            "road_score": vehicle.road_score,
            "family_score": vehicle.family_score,
            "app_score": vehicle.app_score,
            "vehicle_type": "car",
        }
        for vehicle in SAMPLE_VEHICLES
    )
    ids = [int(row["id"]) for row in rows]
    if len(rows) != 34 or len(set(ids)) != 34 or set(ids) != EXPECTED_CATALOG_IDS:
        raise ValueError("SAMPLE_VEHICLES does not define the canonical 34 unique IDs")
    return rows


def _read_catalog_rows(connection) -> tuple[Mapping[str, object], ...]:
    return tuple(
        connection.execute(
            text(
                """SELECT id,brand,model,year,vehicle_type
                FROM vehicles ORDER BY id"""
            )
        ).mappings().all()
    )


def _validate_catalog_rows(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    canonical = {
        int(row["id"]): row for row in _canonical_catalog_rows()
    }
    ids = [int(row["id"]) for row in rows]
    found = set(ids)
    missing = sorted(EXPECTED_CATALOG_IDS - found)
    extra = sorted(found - EXPECTED_CATALOG_IDS)
    duplicates = sorted(
        item for item, count in Counter(ids).items() if count > 1
    )
    identity_mismatches = [
        int(row["id"])
        for row in rows
        if int(row["id"]) in canonical
        and (
            str(row["brand"]) != str(canonical[int(row["id"])]["brand"])
            or str(row["model"]) != str(canonical[int(row["id"])]["model"])
            or int(row["year"]) != int(canonical[int(row["id"])]["year"])
            or str(row["vehicle_type"]) != "car"
        )
    ]
    if (
        len(rows) != 34
        or len(found) != 34
        or missing
        or extra
        or duplicates
        or identity_mismatches
    ):
        raise ValueError(
            "demo automobile catalog postcondition failed "
            f"(count={len(rows)}, distinct={len(found)}, missing={missing}, "
            f"extra={extra}, duplicates={duplicates}, "
            f"identity_mismatches={identity_mismatches})"
        )
    return {
        "status": "passed",
        "automobiles": len(rows),
        "distinct_vehicle_ids": len(found),
        "vehicle_ids": ids,
        "missing_vehicle_ids": missing,
        "extra_vehicle_ids": extra,
        "duplicate_vehicle_ids": duplicates,
        "identity_mismatches": identity_mismatches,
        "canonical_source": "app.sample_data.VEHICLES",
    }


def bootstrap_demo_catalog(engine: Engine) -> dict[str, object]:
    """Persiste somente SAMPLE_VEHICLES e confirma a pós-condição no alvo."""
    if engine.dialect.name != "postgresql":
        raise ValueError("demo catalog bootstrap refuses non-PostgreSQL engines")
    transaction_result = "not_needed"
    with engine.connect() as connection:
        existing = _read_catalog_rows(connection)
        marker_exists = bool(
            connection.execute(
                text(
                    """SELECT EXISTS (
                    SELECT 1 FROM sigra_schema_migrations WHERE version=:version)"""
                ),
                {"version": DEMO_CATALOG_MARKER},
            ).scalar_one()
        )
    if existing:
        _validate_catalog_rows(existing)
    if not existing or not marker_exists:
        with engine.begin() as connection:
            if not existing:
                connection.execute(
                    models.Vehicle.__table__.insert(),
                    list(_canonical_catalog_rows()),
                )
            materialized = _read_catalog_rows(connection)
            _validate_catalog_rows(materialized)
            connection.execute(
                text(
                    """INSERT INTO sigra_schema_migrations (version)
                    VALUES (:version) ON CONFLICT (version) DO NOTHING"""
                ),
                {"version": DEMO_CATALOG_MARKER},
            )
        transaction_result = "committed"
    final = validate_catalog(engine)
    return {
        "status": "applied" if not existing else "already_applied",
        "function": "bootstrap_demo_catalog",
        "seed_source": "app.sample_data.VEHICLES",
        "transaction": transaction_result,
        "database_modified": transaction_result == "committed",
        "catalog": final,
    }


def validate_catalog(engine: Engine) -> dict[str, object]:
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        rows = _read_catalog_rows(connection)
        marker = bool(
            connection.execute(
                text(
                    """SELECT EXISTS (
                    SELECT 1 FROM sigra_schema_migrations
                    WHERE version=:version)"""
                ),
                {"version": DEMO_CATALOG_MARKER},
            ).scalar_one()
        )
    if revision != EXPECTED_ALEMBIC_HEAD:
        raise ValueError("demo database is not at the expected Alembic head")
    validation = _validate_catalog_rows(rows)
    if set(FIPE_REFERENCE_PROFILES) != EXPECTED_CATALOG_IDS:
        raise ValueError("FIPE reference profile catalog is inconsistent")
    if not marker:
        raise ValueError("PostgreSQL demo catalog bootstrap marker is missing")
    return {
        **validation,
        "alembic_head": revision,
        "bootstrap_marker": DEMO_CATALOG_MARKER,
        "provenance": DEMO_PROVENANCE,
    }


def _load_fipe_cache() -> tuple[dict[str, object], ...]:
    cache_path = PROJECT_ROOT / "backend" / "data" / "fipe_cache.json"
    rows = tuple(json.loads(cache_path.read_text(encoding="utf-8")))
    if len(rows) != 34:
        raise ValueError("FIPE local cache must contain exactly 34 records")
    if {int(row["vehicle_id"]) for row in rows} != EXPECTED_CATALOG_IDS:
        raise ValueError("FIPE local cache vehicle IDs are inconsistent")
    if any(row.get("retrieval_status") != "live" for row in rows):
        raise ValueError("FIPE local replay accepts only cache rows with live provenance")
    if any("-" not in str(row.get("year_code", "")) for row in rows):
        raise ValueError("FIPE local replay requires complete year_code values")
    return tuple(sorted(rows, key=lambda row: int(row["vehicle_id"])))


def _format_brl(value: object) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    whole, fraction = f"{amount:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"R$ {grouped},{fraction}"


class CachedFipeClient:
    """Replay local de respostas FIPE live, sem rede e sem alterar o cache."""

    def __init__(self, catalog: Mapping[int, Mapping[str, object]]) -> None:
        self.responses: dict[str, FipeResponse] = {}
        for row in _load_fipe_cache():
            vehicle_id = int(row["vehicle_id"])
            target = FipeTarget("car", str(row["code"]), str(row["year_code"]))
            collected_at = datetime.fromisoformat(str(row["retrieved_at"]))
            if collected_at.tzinfo is None:
                collected_at = collected_at.replace(tzinfo=UTC)
            payload = {
                "price": _format_brl(row["price"]),
                "brand": str(catalog[vehicle_id]["brand"]),
                "model": str(row["model"]),
                "modelYear": int(str(row["year_code"]).split("-", 1)[0]),
                "fuel": "Flex",
                "codeFipe": str(row["code"]),
                "referenceMonth": str(row["reference_month"]),
                "fuelAcronym": "F",
                "vehicleType": 1,
            }
            self.responses[target.endpoint] = FipeResponse(
                endpoint=target.endpoint,
                status_code=200,
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                collected_at=collected_at,
            )

    def fetch(self, endpoint: str) -> FipeResponse:
        try:
            return self.responses[endpoint]
        except KeyError as exc:
            raise ValueError("FIPE cache replay received an unknown endpoint") from exc


def _catalog_by_id(engine: Engine) -> dict[int, Mapping[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id,brand,model,year FROM vehicles")
        ).mappings().all()
    return {int(row["id"]): row for row in rows}


def _activation_reconciliation_plan(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Escolhe o candidato valido mais recente sem descartar historico."""
    valid = [dict(item) for item in candidates if bool(item.get("valid"))]
    if not valid:
        raise ValueError("Gold activation reconciliation requires a valid complete candidate")

    canonical = max(
        valid,
        key=lambda item: (
            str(item.get("published_at") or item.get("created_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("dataset_version") or ""),
        ),
    )
    canonical_version = str(canonical["dataset_version"])
    active_versions = tuple(
        sorted(
            str(item["dataset_version"])
            for item in candidates
            if bool(item.get("active"))
        )
    )
    preserved_versions = tuple(
        sorted(str(item["dataset_version"]) for item in candidates)
    )
    return {
        "canonical_dataset_version": canonical_version,
        "canonical_reason": (
            "latest published valid complete dataset under the existing source contract"
        ),
        "activation_required": active_versions != (canonical_version,),
        "deactivate_dataset_versions": tuple(
            item for item in active_versions if item != canonical_version
        ),
        "preserved_dataset_versions": preserved_versions,
    }


def _fipe_activation_candidates(connection: Connection) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        text(
            """SELECT d.dataset_version,d.publication_run_id::text AS pipeline_run_id,
                   d.dataset_fingerprint,d.status,d.is_active AS active,
                   d.base_quality_status AS quality_status,d.created_at,
                   d.published_at,d.retired_at,d.expected_vehicle_count,
                   d.published_vehicle_count,d.blocked_vehicle_count,
                   d.coverage_percentage,
                   r.source_reference,snapshots.snapshot_count
            FROM gold.vehicle_feature_dataset AS d
            JOIN meta.pipeline_run AS r
              ON r.pipeline_run_id=d.publication_run_id
            CROSS JOIN LATERAL (
                SELECT COUNT(*) AS snapshot_count
                FROM gold.vehicle_features_snapshot AS s
                WHERE s.dataset_version=d.dataset_version
            ) AS snapshots
            ORDER BY d.created_at,d.dataset_version"""
        )
    ).mappings()
    candidates: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["complete"] = bool(
            int(item["expected_vehicle_count"]) == 34
            and int(item["published_vehicle_count"]) == 34
            and int(item["blocked_vehicle_count"]) == 0
            and int(item["snapshot_count"]) == 34
        )
        item["valid"] = bool(
            item["status"] in {"published", "retired"}
            and item["published_at"] is not None
            and item["quality_status"] == "passed"
            and item["complete"]
            and item["source_reference"] == FIPE_SOURCE_REFERENCE
        )
        item["technical_key"] = item["dataset_version"]
        candidates.append(item)
    return tuple(candidates)


def _source_activation_summary(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    materialized = tuple(dict(item) for item in candidates)
    return {
        "total_datasets": len(materialized),
        "valid_datasets": sum(bool(item["valid"]) for item in materialized),
        "active_datasets": sum(bool(item["active"]) for item in materialized),
        "active_valid_datasets": sum(
            bool(item["active"] and item["valid"]) for item in materialized
        ),
        "candidates": materialized,
    }


def _pbev_activation_candidates(connection: Connection) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        text(
            """SELECT d.dataset_version,d.publication_run_id::text AS pipeline_run_id,
                   d.dataset_fingerprint,d.status,d.is_active_shadow AS active,
                   d.quality_status,d.created_at,d.published_at,d.retired_at,
                   d.universe_count,d.matched_count,d.ambiguous_count,
                   d.rejected_count,d.not_found_count,d.pending_count,
                   d.published_count,snapshots.snapshot_count
            FROM gold.vehicle_efficiency_dataset AS d
            CROSS JOIN LATERAL (
                SELECT COUNT(*) AS snapshot_count
                FROM gold.vehicle_efficiency_snapshot AS s
                WHERE s.dataset_version=d.dataset_version
            ) AS snapshots
            ORDER BY d.created_at,d.dataset_version"""
        )
    ).mappings()
    candidates: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["complete"] = bool(
            int(item["universe_count"]) == 34
            and int(item["matched_count"]) == 18
            and int(item["ambiguous_count"]) == 6
            and int(item["rejected_count"]) == 3
            and int(item["not_found_count"]) == 3
            and int(item["pending_count"]) == 4
            and int(item["published_count"]) == 18
            and int(item["snapshot_count"]) == 18
        )
        item["valid"] = bool(
            item["status"] in {"shadow_published", "retired"}
            and item["published_at"] is not None
            and item["quality_status"] == "passed"
            and item["complete"]
        )
        item["technical_key"] = item["dataset_version"]
        candidates.append(item)
    return tuple(candidates)


def _anp_activation_candidates(connection: Connection) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        text(
            """SELECT d.dataset_version,d.publication_run_id::text AS pipeline_run_id,
                   d.dataset_fingerprint,d.status,d.is_active_shadow AS active,
                   d.quality_status,d.created_at,d.published_at,d.retired_at,
                   d.reference_period_start,d.reference_period_end,
                   d.observation_count,d.snapshot_count AS declared_snapshot_count,
                   snapshots.snapshot_count
            FROM gold.anp_fuel_price_dataset AS d
            CROSS JOIN LATERAL (
                SELECT COUNT(*) AS snapshot_count
                FROM gold.anp_fuel_price_snapshot AS s
                WHERE s.dataset_version=d.dataset_version
            ) AS snapshots
            ORDER BY d.created_at,d.dataset_version"""
        )
    ).mappings()
    candidates: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["complete"] = bool(
            int(item["observation_count"]) > 0
            and int(item["declared_snapshot_count"]) > 0
            and int(item["snapshot_count"]) == int(item["declared_snapshot_count"])
        )
        item["valid"] = bool(
            item["status"] in {"shadow_published", "retired"}
            and item["published_at"] is not None
            and item["quality_status"] == "passed"
            and item["complete"]
        )
        item["technical_key"] = item["dataset_version"]
        candidates.append(item)
    return tuple(candidates)


def _activation_state(connection: Connection) -> dict[str, object]:
    return {
        "fipe": _source_activation_summary(_fipe_activation_candidates(connection)),
        "pbev": _source_activation_summary(_pbev_activation_candidates(connection)),
        "anp": _source_activation_summary(_anp_activation_candidates(connection)),
    }


def inspect_demo_gold_source_activations(engine: Engine) -> dict[str, object]:
    """Diagnostico read-only das fontes requeridas pela Gold integrada."""
    with engine.connect() as connection:
        return _activation_state(connection)


def reconcile_demo_gold_source_activations(
    engine: Engine,
    *,
    authorized: bool = False,
) -> dict[str, object]:
    """Reconcilia somente a ativacao FIPE demonstrativa, com opt-in explicito."""
    before = inspect_demo_gold_source_activations(engine)
    affected = tuple(
        source
        for source in ("fipe", "pbev", "anp")
        if int(before[source]["active_valid_datasets"]) != 1
    )
    if not affected:
        return {
            "status": "already_reconciled",
            "authorization_required": True,
            "transaction": "not_needed",
            "before": before,
            "changes": (),
            "after": before,
            "history_preserved": True,
        }
    if not authorized:
        raise ValueError("explicit Gold activation reconciliation authorization is required")
    unsupported = tuple(source for source in affected if source != "fipe")
    if unsupported:
        raise ValueError(
            "Gold activation reconciliation has no safe operation for: "
            + ",".join(unsupported)
        )

    initial_plan = _activation_reconciliation_plan(before["fipe"]["candidates"])
    loader = GoldLoader(engine)
    run_id = uuid4()
    changes: list[dict[str, object]] = []
    with loader.publication_transaction() as connection:
        connection.execute(
            text("SELECT dataset_version FROM gold.vehicle_efficiency_dataset FOR UPDATE")
        ).all()
        connection.execute(
            text("SELECT dataset_version FROM gold.anp_fuel_price_dataset FOR UPDATE")
        ).all()
        active = loader.active_dataset(connection)
        target_version = str(initial_plan["canonical_dataset_version"])
        target = loader.dataset(connection, target_version)
        locked_candidates = _fipe_activation_candidates(connection)
        plan = _activation_reconciliation_plan(locked_candidates)
        if str(plan["canonical_dataset_version"]) != target_version:
            raise ValueError("FIPE canonical dataset changed during reconciliation")
        if target is None or not loader.validate_dataset_snapshot(connection, target):
            raise ValueError("FIPE canonical dataset failed locked snapshot validation")
        if target["base_quality_status"] != "passed":
            raise ValueError("FIPE canonical dataset is not quality-passed")
        if not bool(plan["activation_required"]):
            raise ValueError("FIPE reconciliation became unnecessary during transaction")

        activated_at = loader.database_now(connection)
        connection.execute(
            text(
                """INSERT INTO meta.pipeline_run
                (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                 trigger_type,status,started_at,source_reference,git_commit)
                VALUES (:run,'postgresql_demo_gold_activation_reconciliation',
                        'demo-gold-activation-reconciliation-v1',:dataset,
                        'manual','running',:started,:reference,NULL)"""
            ),
            {
                "run": run_id,
                "dataset": target_version,
                "started": activated_at,
                "reference": FIPE_SOURCE_REFERENCE,
            },
        )
        previous_version = (
            str(active["dataset_version"]) if active is not None else None
        )
        loader.activate_dataset(
            connection,
            run_id,
            target_version,
            previous_dataset_version=previous_version,
            activation_type="rollback" if previous_version is not None else "initial",
            activated_at=activated_at,
        )
        loader.finish_run(
            connection,
            run_id,
            "succeeded",
            expected=int(target["expected_vehicle_count"]),
            inserted=0,
            deduplicated=int(target["published_vehicle_count"]),
            rejected=int(target["blocked_vehicle_count"]),
        )
        final_state = _activation_state(connection)
        for source in ("fipe", "pbev", "anp"):
            if int(final_state[source]["active_valid_datasets"]) != 1:
                raise ValueError(
                    f"{source} reconciliation pre-commit cardinality is inconsistent"
                )
            if int(final_state[source]["active_datasets"]) != 1:
                raise ValueError(f"{source} active uniqueness is inconsistent")
        changes.append(
            {
                "source": "fipe",
                "activated_dataset_version": target_version,
                "deactivated_dataset_versions": plan["deactivate_dataset_versions"],
                "activation_run_id": str(run_id),
                "canonical_reason": plan["canonical_reason"],
                "preserved_dataset_versions": plan["preserved_dataset_versions"],
            }
        )

    after = inspect_demo_gold_source_activations(engine)
    inconsistent_after = tuple(
        source
        for source in ("fipe", "pbev", "anp")
        if int(after[source]["active_valid_datasets"]) != 1
    )
    if inconsistent_after:
        raise ValueError(
            "Gold source cardinality remains inconsistent after commit: "
            + ",".join(inconsistent_after)
        )
    return {
        "status": "succeeded",
        "authorization_required": True,
        "transaction": "committed",
        "before": before,
        "changes": tuple(changes),
        "after": after,
        "history_preserved": True,
    }


def _active_valid_demo_fipe(engine: Engine) -> Mapping[str, object] | None:
    report = inspect_demo_gold_source_activations(engine)["fipe"]
    active_valid = tuple(
        item
        for item in report["candidates"]
        if bool(item["active"] and item["valid"])
    )
    return active_valid[0] if len(active_valid) == 1 else None


def materialize_fipe(engine: Engine) -> dict[str, object]:
    catalog = _catalog_by_id(engine)
    cache = _load_fipe_cache()
    targets = [
        FipeTarget("car", str(row["code"]), str(row["year_code"])) for row in cache
    ]
    result_bronze = run_pipeline(
        targets,
        CachedFipeClient(catalog),
        BronzeLoader(engine),
        trigger_type="backfill",
        source_reference=FIPE_SOURCE_REFERENCE,
    )
    result_silver = run_silver_pipeline(
        SilverLoader(engine),
        trigger_type="backfill",
        source_reference=FIPE_SOURCE_REFERENCE,
    )
    active_valid = _active_valid_demo_fipe(engine)
    if active_valid is None:
        result_gold = _public_result(
            run_gold_publication(
                GoldLoader(engine),
                trigger_type="backfill",
                source_reference=FIPE_SOURCE_REFERENCE,
            )
        )
    else:
        result_gold = {
            "pipeline_run_id": active_valid["pipeline_run_id"],
            "dataset_version": active_valid["dataset_version"],
            "status": "deduplicated",
            "expected_count": active_valid["expected_vehicle_count"],
            "published_count": active_valid["published_vehicle_count"],
            "blocked_count": active_valid["blocked_vehicle_count"],
            "coverage_percentage": _json_value(active_valid["coverage_percentage"]),
            "fingerprint": active_valid["dataset_fingerprint"],
            "issues_recorded": 0,
            "errors": [],
        }
    if result_bronze.status != "succeeded":
        raise ValueError("FIPE Bronze local replay did not succeed")
    if result_silver.status != "succeeded":
        raise ValueError("FIPE Silver local replay did not succeed")
    if result_gold["status"] not in {"succeeded", "deduplicated"}:
        raise ValueError("FIPE Gold local replay did not publish")
    return {
        "provenance": "versioned_fipe_cache_with_live_status",
        "bronze": _public_result(result_bronze),
        "silver": _public_result(result_silver),
        "gold": result_gold,
    }


def build_demo_pbev_fixture(
    targets: Sequence[ExternalVehicleIdentity],
) -> tuple[PbevAssetParseResult, tuple[ExternalVehicleMapping, ...]]:
    if len(targets) != 34:
        raise ValueError("PBEV demo fixture requires exactly 34 catalog targets")
    matched_rows: list[ParsedPbevRow] = []
    row_hash_by_target: dict[str, str] = {}
    for position, target in enumerate(targets[:18], start=1):
        fossil_city = Decimal("10.0000") + Decimal(position % 5) / Decimal("10")
        fossil_highway = fossil_city + Decimal("2.0000")
        ethanol_city = Decimal("7.0000") + Decimal(position % 4) / Decimal("10")
        ethanol_highway = ethanol_city + Decimal("1.8000")
        raw_payload = {
            "provenance": DEMO_PROVENANCE,
            "target_identity_hash": target.identity_hash,
            "brand": target.brand_name,
            "model": target.model_name,
            "fossil_city_km_l": str(fossil_city),
            "fossil_highway_km_l": str(fossil_highway),
            "ethanol_city_km_l": str(ethanol_city),
            "ethanol_highway_km_l": str(ethanol_highway),
        }
        row_hash = _sha256(raw_payload)
        row_hash_by_target[target.identity_hash] = row_hash
        matched_rows.append(
            ParsedPbevRow(
                raw=PbevRawRow(
                    cycle_year=2022,
                    page_number=1,
                    row_number=position,
                    parser_version=PBEV_PARSER_VERSION,
                    layout_family="demo_fixture_layout_v1",
                    schema_fingerprint=_sha256("sigra-demo-pbev-schema-v1"),
                    raw_cells=tuple(str(value) for value in raw_payload.values()),
                    raw_text=f"DEMO_FIXTURE {target.brand_name} {target.model_name}",
                    row_hash=row_hash,
                    extraction_status="parsed",
                    extraction_method="positioned_text",
                    source_record_key=f"demo-fixture:{target.external_catalog_reference}",
                ),
                category_name=target.body_style or "demo_vehicle",
                brand_name=target.brand_name,
                model_name=target.model_name,
                version_name=target.version_name,
                motor_description=target.motor_description,
                transmission_code=target.transmission_type,
                propulsion_type="internal_combustion",
                fuel_type="flex",
                air_conditioning_code=None,
                steering_assistance_code=None,
                emission_schema_version="demo_fixture_v1",
                emission_raw=(DEMO_PROVENANCE,),
                consumption_raw=(
                    str(ethanol_city),
                    str(ethanol_highway),
                    str(fossil_city),
                    str(fossil_highway),
                ),
                ethanol_city_km_l=ethanol_city,
                ethanol_highway_km_l=ethanol_highway,
                fossil_city_km_l=fossil_city,
                fossil_highway_km_l=fossil_highway,
                energy_mj_km=Decimal("2.0000") + Decimal(position) / Decimal("100"),
                pbe_relative_class="DEMO",
                pbe_absolute_class="DEMO",
                conpet_seal=False,
            )
        )

    asset_seed = {
        "provenance": DEMO_PROVENANCE,
        "official_evidence": False,
        "target_hashes": [target.identity_hash for target in targets[:18]],
    }
    asset = SourceAsset(
        pipeline_run_id=None,
        cycle_year=2022,
        official_page_url="https://demo.invalid/sigra/pbev",
        download_url_sanitized="https://demo.invalid/sigra/pbev/demo-fixture.pdf",
        document_title="SIGRA PBEV synthetic demo_fixture (not official evidence)",
        accessed_at=FIXED_AT,
        content_type="application/pdf",
        byte_length=len(json.dumps(asset_seed, sort_keys=True).encode("utf-8")),
        page_count=1,
        sha256=_sha256(asset_seed),
        layout_family="demo_fixture_layout_v1",
        document_metadata={
            "provenance": DEMO_PROVENANCE,
            "official_evidence": False,
            "synthetic": True,
        },
        storage_mode="metadata_only",
        license_code="DEMO_FIXTURE",
        attribution_text="SIGRA synthetic demo_fixture; not an Inmetro publication",
        license_url="https://demo.invalid/sigra/fixture-license",
        asset_status="accepted",
        validation_details={
            "provenance": DEMO_PROVENANCE,
            "official_evidence": False,
            "acknowledgement_required": True,
        },
    )
    parse_result = PbevAssetParseResult(
        asset=asset,
        rows=tuple(matched_rows),
        pages_processed=1,
        tables_found=1,
        rows_rejected=0,
    )

    statuses = (
        (MappingStatus.MATCHED,) * 18
        + (MappingStatus.AMBIGUOUS,) * 6
        + (MappingStatus.REJECTED,) * 3
        + (MappingStatus.NOT_FOUND,) * 3
        + (MappingStatus.PENDING,) * 4
    )
    methods = {
        MappingStatus.MATCHED: MatchMethod.EXACT_RULE,
        MappingStatus.AMBIGUOUS: MatchMethod.SCORED_RULE,
        MappingStatus.REJECTED: MatchMethod.CATALOG_CONFLICT,
        MappingStatus.NOT_FOUND: MatchMethod.NO_CANDIDATE,
        MappingStatus.PENDING: MatchMethod.MANUAL_REVIEW,
    }
    mappings = []
    for target, status in zip(targets, statuses, strict=True):
        evidence: dict[str, object] = {
            "provenance": DEMO_PROVENANCE,
            "official_evidence": False,
            "fixture_status": status.value,
        }
        if status is MappingStatus.MATCHED:
            evidence["selected_row_hash"] = row_hash_by_target[target.identity_hash]
        mappings.append(
            ExternalVehicleMapping(
                target_identity_hash=target.identity_hash,
                target_identity_evidence={
                    **dict(target.evidence),
                    "provenance": DEMO_PROVENANCE,
                    "official_evidence": False,
                },
                mapping_status=status,
                match_method=methods[status],
                matcher_version=PBEV_MATCHER_VERSION,
                confidence=Decimal("100.00") if status is MappingStatus.MATCHED else None,
                review_required=status in {
                    MappingStatus.AMBIGUOUS,
                    MappingStatus.REJECTED,
                    MappingStatus.PENDING,
                },
                evidence=evidence,
                decision_reason=f"demo_fixture_{status.value}",
                vehicle_sk=target.vehicle_sk if status is MappingStatus.MATCHED else None,
            )
        )
    return parse_result, tuple(mappings)


def materialize_pbev(engine: Engine) -> dict[str, object]:
    targets = load_current_catalog_targets(engine)
    parse_result, mappings = build_demo_pbev_fixture(targets)
    loader = PbevLoader(engine, methodology_reference=PBEV_METHODOLOGY)
    with loader.cycle_locks((2022,)):
        run_id = loader.start_run(
            "pbev_demo_fixture_shadow",
            "demo-fixture-v1",
            "pbev-demo-fixture-building",
            "backfill",
            PBEV_SOURCE_REFERENCE,
            None,
        )
        try:
            rows, bronze_inserted, bronze_deduplicated = loader.persist_bronze(
                run_id, (parse_result,)
            )
            stored_mappings, observations, mapping_inserted = loader.persist_mappings(
                run_id, mappings, rows
            )
            manifest = (
                {
                    "asset_id": rows[0].raw.asset_id,
                    "sha256": parse_result.asset.sha256,
                    "cycle_year": 2022,
                    "storage_mode": "metadata_only",
                    "provenance": DEMO_PROVENANCE,
                    "official_evidence": False,
                    "document_bytes_persisted": False,
                },
            )
            report = build_coverage_report(
                dataset_version="pbev-demo-fixture-v1",
                asset_manifest=manifest,
                targets=targets,
                mappings=stored_mappings,
                field_coverage={
                    "consumption": {
                        "eligible": 18,
                        "present": 18,
                        "coverage_percentage": "100.00",
                        "provenance": DEMO_PROVENANCE,
                    }
                },
                generated_at=FIXED_AT,
            )
            enforce_audited_pilot_baseline(
                stored_mappings,
                baseline_applicable=True,
            )
            validate_shadow_rows(
                stored_mappings,
                [item.vehicle_sk for item in observations],
            )
            dataset_version, deduplicated = loader.publish_shadow(
                run_id,
                report,
                stored_mappings,
                observations,
            )
            loader.finish_run(
                run_id,
                "succeeded",
                received=len(targets),
                inserted=bronze_inserted + mapping_inserted,
                deduplicated=bronze_deduplicated + (len(observations) if deduplicated else 0),
                rejected=0,
            )
        except Exception as exc:
            loader.finish_run(
                run_id,
                "failed",
                received=len(targets),
                inserted=0,
                deduplicated=0,
                rejected=0,
                error=sanitize(exc),
            )
            raise
    counts = Counter(item.mapping_status.value for item in stored_mappings)
    return {
        "status": "deduplicated" if deduplicated else "succeeded",
        "dataset_version": dataset_version,
        "pipeline_run_id": str(run_id),
        "provenance": DEMO_PROVENANCE,
        "official_evidence": False,
        "storage_mode": "metadata_only",
        "document_bytes_persisted": False,
        "mappings": dict(sorted(counts.items())),
        "published_observations": len(observations),
        "coverage_percentage": format(report.coverage_percentage, "f"),
    }


def _anp_csv_content() -> bytes:
    products = (
        ("GASOLINA", "5,7000"),
        ("GASOLINA ADITIVADA", "6,1000"),
        ("ETANOL", "4,2000"),
    )
    rows = []
    for index, (product, price) in enumerate(products, start=1):
        rows.append(
            {
                "Regiao - Sigla": "SE",
                "Estado - Sigla": "SP",
                "Municipio": "São Paulo",
                "Revenda": f"SIGRA DEMO FIXTURE POSTO {index}",
                "CNPJ da Revenda": "",
                "Nome da Rua": "Rua Demonstrativa",
                "Numero Rua": str(index),
                "Complemento": "DADO SINTETICO",
                "Bairro": "Centro Demonstrativo",
                "Cep": "00000-000",
                "Produto": product,
                "Data da Coleta": "04/08/2026",
                "Valor de Venda": price,
                "Valor de Compra": "",
                "Unidade de Medida": "R$ / litro",
                "Bandeira": "DEMO_FIXTURE",
            }
        )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=ANP_EXPECTED_HEADER,
        delimiter=";",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


def _resolve_demo_anp_source(source_reference: str) -> tuple[str, str, str]:
    if source_reference != ANP_SOURCE_REFERENCE:
        raise ValueError("unknown ANP demo fixture reference")
    return (
        "https://demo.invalid/sigra/anp",
        "https://demo.invalid/sigra/anp/demo-fixture.csv",
        "sigra-demo-fixture-anp.csv",
    )


class DemoAnpClient:
    def __init__(self) -> None:
        self.content = _anp_csv_content()

    def download(
        self,
        *,
        source_reference: str,
        official_page_url: str,
        download_url: str,
        filename: str,
        destination_directory: Path,
    ) -> DownloadedAnpAsset:
        path = Path(destination_directory) / filename
        path.write_bytes(self.content)
        return DownloadedAnpAsset(
            source_reference=source_reference,
            official_page_url=official_page_url,
            download_url_sanitized=download_url,
            filename=filename,
            path=path,
            collected_at=FIXED_AT,
            http_status=200,
            content_type="text/csv",
            byte_length=len(self.content),
            etag=None,
            last_modified=None,
            sha256=hashlib.sha256(self.content).hexdigest(),
        )


def materialize_anp(engine: Engine) -> dict[str, object]:
    result = run_anp_pipeline(
        AnpFuelPriceLoader(engine),
        AnpExecutionOptions(
            source_reference=ANP_SOURCE_REFERENCE,
            trigger_type="backfill",
        ),
        client=DemoAnpClient(),
        source_resolver=_resolve_demo_anp_source,
    )
    if result.status not in {"succeeded", "deduplicated"}:
        raise ValueError("ANP demo fixture did not publish")
    return {
        **_public_result(result),
        "provenance": DEMO_PROVENANCE,
        "official_evidence": False,
        "storage_mode": "metadata_only",
        "geography_level": DEMO_GEOGRAPHY_LEVEL,
        "geography_key": DEMO_GEOGRAPHY_KEY,
        "week_start": DEMO_WEEK_START.isoformat(),
    }


def materialize_integrated(engine: Engine) -> dict[str, object]:
    request = IntegratedPublicationRequest(
        geography_level=DEMO_GEOGRAPHY_LEVEL,
        geography_key=DEMO_GEOGRAPHY_KEY,
        week_start=DEMO_WEEK_START,
        include_additized=True,
    )
    result = run_integrated_vehicle_cost_pipeline(
        IntegratedVehicleCostLoader(engine),
        IntegratedVehicleCostOptions(
            request=request,
            trigger_type="backfill",
        ),
    )
    if result.status not in {"succeeded", "deduplicated"}:
        raise ValueError("integrated Gold demo dataset is not eligible")
    return _public_result(result)


def validate_materialized_gold(engine: Engine) -> dict[str, object]:
    with engine.connect() as connection:
        fipe = connection.execute(
            text(
                """SELECT dataset_version,status,is_active,
                       expected_vehicle_count,published_vehicle_count,
                       blocked_vehicle_count,coverage_percentage,base_quality_status
                FROM gold.vehicle_feature_dataset WHERE is_active"""
            )
        ).mappings().one()
        pbev = connection.execute(
            text(
                """SELECT dataset_version,status,is_active_shadow,universe_count,
                       matched_count,ambiguous_count,rejected_count,not_found_count,
                       pending_count,published_count,coverage_percentage,quality_status,
                       source_asset_manifest
                FROM gold.vehicle_efficiency_dataset WHERE is_active_shadow"""
            )
        ).mappings().one()
        anp = connection.execute(
            text(
                """SELECT dataset_version,status,is_active_shadow,observation_count,
                       snapshot_count,quality_status,source_asset_manifest
                FROM gold.anp_fuel_price_dataset WHERE is_active_shadow"""
            )
        ).mappings().one()
        integrated = connection.execute(
            text(
                """SELECT dataset_version,status,is_active_shadow,hard_gate_status,
                       quality_status,coverage_regression_status,
                       catalog_universe_count,pbev_matched_universe_count,
                       published_vehicle_count,excluded_vehicle_count,
                       published_scenario_count,catalog_coverage_pct,pbev_coverage_pct
                FROM gold.integrated_vehicle_cost_dataset WHERE is_active_shadow"""
            )
        ).mappings().one()
        hard_gates = connection.execute(
            text(
                """SELECT status,COUNT(*) AS count
                FROM gold.integrated_vehicle_cost_quality_result
                WHERE dataset_version=:dataset AND rule_kind='hard_gate'
                GROUP BY status ORDER BY status"""
            ),
            {"dataset": integrated["dataset_version"]},
        ).mappings().all()
        statistical = connection.execute(
            text(
                """SELECT status,COUNT(*) AS count
                FROM gold.integrated_vehicle_cost_quality_result
                WHERE dataset_version=:dataset AND rule_kind='statistical_control'
                GROUP BY status ORDER BY status"""
            ),
            {"dataset": integrated["dataset_version"]},
        ).mappings().all()
        view = connection.execute(
            text(
                """SELECT COUNT(*) AS rows,
                       COUNT(DISTINCT vehicle_sk) AS vehicles,
                       COUNT(DISTINCT fuel_scenario_code) AS fuel_scenarios,
                       COUNT(DISTINCT dataset_version) AS datasets
                FROM gold.integrated_vehicle_cost_consumption_v1"""
            )
        ).mappings().one()
        lineage = connection.execute(
            text(
                """SELECT COUNT(*) AS demo_observations
                FROM silver.vehicle_efficiency_observation
                WHERE methodology_reference=:methodology"""
            ),
            {"methodology": PBEV_METHODOLOGY},
        ).mappings().one()

    pbev_manifest = pbev["source_asset_manifest"]
    anp_manifest = anp["source_asset_manifest"]
    checks = {
        "fipe": bool(
            fipe["status"] == "published"
            and fipe["is_active"]
            and fipe["expected_vehicle_count"] == 34
            and fipe["published_vehicle_count"] == 34
            and fipe["blocked_vehicle_count"] == 0
            and fipe["base_quality_status"] == "passed"
        ),
        "pbev": bool(
            pbev["status"] == "shadow_published"
            and pbev["is_active_shadow"]
            and pbev["universe_count"] == 34
            and pbev["matched_count"] == 18
            and pbev["ambiguous_count"] == 6
            and pbev["rejected_count"] == 3
            and pbev["not_found_count"] == 3
            and pbev["pending_count"] == 4
            and pbev["published_count"] == 18
            and pbev["quality_status"] == "passed"
            and pbev_manifest[0].get("provenance") == DEMO_PROVENANCE
            and not pbev_manifest[0].get("official_evidence")
            and lineage["demo_observations"] == 18
        ),
        "anp": bool(
            anp["status"] == "shadow_published"
            and anp["is_active_shadow"]
            and anp["observation_count"] == 3
            and anp["quality_status"] == "passed"
            and anp_manifest[0].get("source_reference") == ANP_SOURCE_REFERENCE
        ),
        "integrated": bool(
            integrated["status"] == "shadow_published"
            and integrated["is_active_shadow"]
            and integrated["hard_gate_status"] == "passed"
            and integrated["quality_status"] == "passed"
            and integrated["coverage_regression_status"] != "manual_review_required"
            and integrated["catalog_universe_count"] == 34
            and integrated["pbev_matched_universe_count"] == 18
            and integrated["published_vehicle_count"] == 18
            and integrated["excluded_vehicle_count"] == 16
            and integrated["published_scenario_count"] == 54
        ),
        "quality": (
            {str(row["status"]): int(row["count"]) for row in hard_gates}
            == {"passed": 29}
            and {str(row["status"]): int(row["count"]) for row in statistical}
            == {"not_calibrated": 7}
        ),
        "view": bool(
            view["rows"] == 54
            and view["vehicles"] == 18
            and view["fuel_scenarios"] == 3
            and view["datasets"] == 1
        ),
    }
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise ValueError(f"demo Gold validation failed: {failed}")
    return {
        "status": "passed",
        "checks": checks,
        "fipe": _json_value(dict(fipe)),
        "pbev": {
            **_json_value({key: value for key, value in dict(pbev).items() if key != "source_asset_manifest"}),
            "provenance": DEMO_PROVENANCE,
            "official_evidence": False,
            "methodology_reference": PBEV_METHODOLOGY,
        },
        "anp": {
            **_json_value({key: value for key, value in dict(anp).items() if key != "source_asset_manifest"}),
            "provenance": DEMO_PROVENANCE,
            "official_evidence": False,
        },
        "integrated": _json_value(dict(integrated)),
        "quality": {
            "hard_gates": _json_value(hard_gates),
            "statistical_controls": _json_value(statistical),
        },
        "consumption_view": _json_value(dict(view)),
    }


def materialize_demo_gold(engine: Engine) -> dict[str, object]:
    catalog = validate_catalog(engine)
    first = {
        "fipe": materialize_fipe(engine),
        "pbev": materialize_pbev(engine),
        "anp": materialize_anp(engine),
    }
    first["integrated"] = materialize_integrated(engine)
    first_validation = validate_materialized_gold(engine)

    second = {
        "fipe": materialize_fipe(engine),
        "pbev": materialize_pbev(engine),
        "anp": materialize_anp(engine),
    }
    second["integrated"] = materialize_integrated(engine)
    final_validation = validate_materialized_gold(engine)
    if first["fipe"]["gold"]["dataset_version"] != second["fipe"]["gold"]["dataset_version"]:
        raise ValueError("FIPE Gold idempotency failed")
    if first["pbev"]["dataset_version"] != second["pbev"]["dataset_version"]:
        raise ValueError("PBEV shadow idempotency failed")
    if first["anp"]["dataset_version"] != second["anp"]["dataset_version"]:
        raise ValueError("ANP shadow idempotency failed")
    if first["integrated"]["dataset_version"] != second["integrated"]["dataset_version"]:
        raise ValueError("integrated Gold idempotency failed")
    return {
        "status": "succeeded",
        "mode": "synthetic_demo_acknowledged",
        "catalog": catalog,
        "first_execution": first,
        "first_validation": first_validation,
        "second_execution": second,
        "final_validation": final_validation,
        "idempotency": {
            "status": "passed",
            "same_fipe_dataset": True,
            "same_pbev_dataset": True,
            "same_anp_dataset": True,
            "same_integrated_dataset": True,
        },
        "carpedia": {
            "required_by_integrated_contract": False,
            "executed": False,
        },
        "backend_frontend_gate": "eligible_integrated_dataset_available",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap local demonstrativo FIPE/PBEV/ANP/Gold integrada"
    )
    parser.add_argument(
        "--acknowledge-synthetic-demo",
        action="store_true",
        help="Confirma que PBEV/ANP sao fixtures sinteticas e nao dados oficiais.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--bootstrap-catalog",
        action="store_true",
        help="Persiste somente os 34 SAMPLE_VEHICLES no PostgreSQL demonstrativo.",
    )
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="Valida catalogo e Gold existente sem escrever no banco.",
    )
    mode.add_argument(
        "--reconcile-gold-activations",
        action="store_true",
        help="Reconcilia ativacao Gold demonstrativa com autorizacao explicita.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = None
    try:
        raw_url, target = configured_demo_database_url()
        engine = create_engine(
            raw_url,
            pool_pre_ping=True,
            connect_args={"options": "-c timezone=UTC"},
        )
        if args.bootstrap_catalog:
            if not args.acknowledge_synthetic_demo:
                raise ValueError("--acknowledge-synthetic-demo is required before writes")
            report = {
                "target": target,
                **bootstrap_demo_catalog(engine),
            }
        elif args.validate_only:
            report = {
                "status": "passed",
                "target": target,
                "catalog": validate_catalog(engine),
                "materialized": validate_materialized_gold(engine),
            }
        elif args.reconcile_gold_activations:
            if not args.acknowledge_synthetic_demo:
                raise ValueError("--acknowledge-synthetic-demo is required before writes")
            report = {
                "target": target,
                **reconcile_demo_gold_source_activations(engine, authorized=True),
            }
        else:
            if not args.acknowledge_synthetic_demo:
                raise ValueError("--acknowledge-synthetic-demo is required before writes")
            report = {
                "target": target,
                **materialize_demo_gold(engine),
            }
        print(json.dumps(_json_value(report), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {"status": "blocked", "error": sanitize(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
