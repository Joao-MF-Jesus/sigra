from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from data_platform.carpedia.pipeline import CarpediaExecutionOptions, run_carpedia_pipeline
from data_platform.carpedia.loader import (
    CarpediaVehicleSpecsLoader,
    _mapping_decision_is_publishable,
)
from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_MATCHER_VERSION,
    CarpediaAttribute,
    CarpediaMappingStatus,
    CarpediaRequest,
    CarpediaTarget,
    DownloadedCarpediaAsset,
    VehicleIdentityCandidate,
)
from data_platform.ingestion.carpedia.client import (
    CarpediaApiClient,
    CarpediaDownloadPolicy,
)
from data_platform.ingestion.carpedia.parser import CarpediaJsonParser
from data_platform.quality.carpedia_checks import (
    build_snapshots,
    evaluate_quality,
    require_hard_gates,
)
from data_platform.transformation.carpedia import build_specification, normalize_attribute, normalize_text


API_KEY = "cpk_" + "a" * 48


def _payload(*, version: str = "ONIX 1.0", include_secret: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "ref": "2026-08",
        "ano": 2021,
        "versao": {
            "id": 12345,
            "marca": "Chevrolet",
            "modelo": "Onix",
            "nome": version,
        },
        "secoes": [
            {
                "titulo": "Motor",
                "itens": [
                    {"label": "Potência", "valor": "116 cv"},
                    {"label": "Cilindrada", "valor": "999 cm³"},
                    {"label": "Combustível", "valor": "Flex"},
                ],
            },
            {
                "titulo": "Dimensões",
                "itens": [
                    {"label": "Comprimento", "valor": "4.163 mm"},
                    {"label": "Lugares", "valor": "5"},
                ],
            },
        ],
        "consumo": {"cidade": "12,0 km/l", "estrada": "15,0 km/l"},
        "fonte": {"fonte": "Carpedia", "em": "2026-08-20"},
    }
    if include_secret:
        payload["authorization"] = "Bearer never-persist"
        payload["callback"] = "https://" + "user:password@" + "example.test/path?token=secret"
    return payload


def _asset(path: Path, payload: dict[str, object]) -> DownloadedCarpediaAsset:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    path.write_bytes(encoded)
    return DownloadedCarpediaAsset(
        request=CarpediaRequest(
            "vehicle_specification",
            "/api/v1/ficha/12345/2021",
            external_vehicle_id=12345,
            source_reference="12345:2021",
        ),
        path=path,
        collected_at=datetime(2026, 8, 20, tzinfo=UTC),
        http_status=200,
        content_type="application/json",
        byte_length=len(encoded),
        sha256="a" * 64,
    )


def _candidate(vehicle_sk: int = 77, *, version: str = "ONIX 1.0") -> VehicleIdentityCandidate:
    return VehicleIdentityCandidate(
        vehicle_sk=vehicle_sk,
        brand_name="Chevrolet",
        model_name="Onix",
        version_name=version,
        model_year=2021,
        is_zero_km=False,
        fuel_type="flex",
    )


class _Result:
    def __init__(self, *, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def scalar_one(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class _Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        return _Transaction(self.connection)

    def connect(self):
        return _Transaction(self.connection)


def _persistable_specification(tmp_path, *, vehicle_sk=77, mapping_id=None, specification_id=None):
    parsed = CarpediaJsonParser().parse(_asset(tmp_path / f"asset-{vehicle_sk}.json", _payload()))
    parsed = replace(
        parsed,
        raw=replace(parsed.raw, asset_id=10, raw_record_id=20, pipeline_run_id=uuid4()),
    )
    specification = build_specification(parsed, [_candidate(vehicle_sk)])
    mapping = replace(specification.mapping, mapping_decision_id=mapping_id)
    return replace(specification, mapping=mapping, specification_id=specification_id)


def _mapping_row(specification, *, mapping_id=30, matcher_version=CARPEDIA_MATCHER_VERSION):
    return {
        "mapping_decision_id": mapping_id,
        "mapping_status": specification.mapping.status.value,
        "match_method": specification.mapping.match_method,
        "vehicle_sk": specification.mapping.vehicle_sk,
        "confidence": specification.mapping.confidence,
        "review_required": specification.mapping.review_required,
        "matcher_version": matcher_version,
        "identity_evidence": specification.mapping.identity_evidence,
        "candidate_evidence": list(specification.mapping.candidate_evidence),
        "decision_reason": specification.mapping.decision_reason,
    }


def _specification_row(specification, *, specification_id=40, mapping_id=30):
    return {
        "specification_id": specification_id,
        "normalized_fingerprint": specification.normalized_fingerprint,
        "mapping_decision_id": mapping_id,
        "vehicle_sk": specification.mapping.vehicle_sk,
        "mapping_status": specification.mapping.status.value,
    }


def test_parser_normalizer_exact_match_decimal_and_sanitization(tmp_path):
    parsed = CarpediaJsonParser().parse(_asset(tmp_path / "asset.json", _payload(include_secret=True)))
    specification = build_specification(parsed, [_candidate()])

    assert specification.mapping.status == CarpediaMappingStatus.MATCHED
    assert specification.mapping.vehicle_sk == 77
    assert specification.attributes["power"] == {
        "value": "85.317855",
        "unit": "kW",
        "source_value": "116 cv",
        "source_unit": "cv",
        "unit_status": "recognized",
        "precision": 0,
    }
    assert specification.attributes["engine_displacement"]["value"] == "999.000000"
    assert specification.attributes["length"]["value"] == "4163.000000"
    assert specification.attributes["seats"]["value"] == "5"
    assert "never-persist" not in repr(parsed.raw.payload)
    assert "password" not in repr(parsed.raw.payload)
    assert normalize_text(" VW - São Paulo ") == "vw sao paulo"
    assert len(specification.source_fingerprint) == len(specification.normalized_fingerprint) == 64


def test_cached_ficha_labels_preserve_units_provenance_and_ignore_manual_boolean(tmp_path):
    payload = {
        "ref": "09-2026",
        "ano": 2020,
        "manual": False,
        "versao": {
            "id": 44709,
            "marca": "Chevrolet",
            "modelo": "Cruze",
            "nome": "CRUZE LT 1.4 16V Turbo Flex 4p Aut.",
        },
        "secoes": [
            {"titulo": "Geral", "itens": [
                {"label": "Carroceria (configuração)", "valor": "Sedã"},
                {"label": "Número de lugares", "valor": "5"},
                {"label": "Combustível", "valor": "Flex"},
            ]},
            {"titulo": "Dimensões e pesos", "itens": [
                {"label": "Comprimento (mm)", "valor": "4665"},
                {"label": "Largura (mm)", "valor": "1807"},
                {"label": "Distância entre-eixos (mm)", "valor": "2700"},
                {"label": "Carga útil (kg)", "valor": "413"},
                {"label": "Volume do porta-malas (l)", "valor": "440"},
            ]},
            {"titulo": "Motor a combustão", "itens": [
                {"label": "Potência máxima (motor a combustão) (cv)", "valor": "153"},
                {"label": "Cilindrada (cm³)", "valor": "1399"},
            ]},
            {"titulo": "Transmissão e tração", "itens": [
                {"label": "Câmbio (tipo)", "valor": "Automático"},
            ]},
            {"titulo": "Consumo e eficiência", "itens": [
                {"label": "Tanque de combustível (l)", "valor": "52"},
            ]},
        ],
        "fonte": {"fonte": "checktudo-ficha-tecnica-2026-07", "em": "2026-07-13"},
    }
    asset = _asset(tmp_path / "ficha.json", payload)
    asset = replace(
        asset,
        request=CarpediaRequest(
            "vehicle_specification",
            "/api/v1/ficha/44709/2020",
            external_vehicle_id=44709,
            source_reference="44709:2020",
        ),
        sha256="b" * 64,
    )
    parsed = CarpediaJsonParser().parse(asset)
    normalized = {item.attribute_code: item for item in map(normalize_attribute, parsed.attributes)}

    assert set(normalized) == {
        "body_style", "seats", "fuel_type", "length", "width", "wheelbase",
        "payload_capacity", "cargo_capacity", "power", "engine_displacement",
        "transmission", "fuel_tank_capacity",
    }
    expected = {
        "body_style": ("Sedã", None),
        "seats": (Decimal("5"), "count"),
        "cargo_capacity": (Decimal("440.000000"), "L"),
        "payload_capacity": (Decimal("413.000000"), "kg"),
        "length": (Decimal("4665.000000"), "mm"),
        "width": (Decimal("1807.000000"), "mm"),
        "wheelbase": (Decimal("2700.000000"), "mm"),
        "engine_displacement": (Decimal("1399.000000"), "cm3"),
        "power": (Decimal("112.531309"), "kW"),
        "transmission": ("Automático", None),
        "fuel_type": ("Flex", None),
        "fuel_tank_capacity": (Decimal("52.000000"), "L"),
    }
    assert {
        code: (item.normalized_value, item.normalized_unit)
        for code, item in normalized.items()
    } == expected
    for item in normalized.values():
        assert item.provenance["origin"] == "carpedia_api_v1"
        assert item.provenance["external_vehicle_id"] == 44709
        assert item.provenance["model_year"] == 2020
        assert item.provenance["response_sha256"] == "b" * 64
        assert item.provenance["field_locator"].startswith("secoes[")
        assert item.provenance["collected_at"] == asset.collected_at.isoformat()
    assert [item.source_label for item in normalized.values()].count("Câmbio (tipo)") == 1
    assert all(item.source_label != "manual" for item in normalized.values())


@pytest.mark.parametrize(
    "source_label,source_value,source_unit",
    [
        ("Comprimento (parsec)", "10", None),
        ("Comprimento (mm)", "10 cm", None),
    ],
)
def test_normalizer_rejects_invalid_or_conflicting_units(source_label, source_value, source_unit):
    result = normalize_attribute(CarpediaAttribute(
        attribute_code="pending_normalization",
        source_section="Dimensões",
        source_label=source_label,
        source_value=source_value,
        source_unit=source_unit,
        normalized_value=None,
        normalized_unit=None,
        precision=None,
        unit_status="pending",
        provenance={"field_locator": "secoes[0].itens[0]"},
    ))
    assert result.attribute_code == "length"
    assert result.normalized_value is None
    assert result.normalized_unit is None
    assert result.unit_status == "unrecognized"


def test_identity_ambiguity_and_conflict_are_not_gold_eligible(tmp_path):
    parsed = CarpediaJsonParser().parse(_asset(tmp_path / "asset.json", _payload()))
    ambiguous = build_specification(parsed, [_candidate(1), _candidate(2)])
    conflict = build_specification(parsed, [_candidate(3, version="ONIX 1.6")])
    missing = build_specification(parsed, [])

    assert ambiguous.mapping.status == CarpediaMappingStatus.AMBIGUOUS
    assert conflict.mapping.status == CarpediaMappingStatus.REJECTED
    assert missing.mapping.status == CarpediaMappingStatus.NOT_FOUND
    assert all(item.mapping.vehicle_sk is None for item in (ambiguous, conflict, missing))
    assert build_snapshots((ambiguous, conflict, missing)) == ()


def test_dry_run_is_pure_and_requires_no_secret_database_network_or_files():
    result = run_carpedia_pipeline(
        None,
        None,
        CarpediaExecutionOptions(targets=(CarpediaTarget(12345, 2021),), dry_run=True),
    )
    assert result.status == "planned"
    assert result.pipeline_run_id is None
    assert result.plan["publication_mode"] == "shadow"
    assert result.plan["targets"] == ["12345:2021"]


def test_pipeline_separates_layers_and_publishes_only_exact_match():
    class StaticClient:
        def fetch(self, request, *, destination_directory):
            path = destination_directory / "fixture.json"
            asset = _asset(path, _payload())
            return replace(asset, request=request)

    class MemoryLoader:
        def __init__(self):
            self.run_id = uuid4()
            self.finished = None

        @contextmanager
        def source_lock(self):
            yield

        def start_run(self, dataset_version, trigger_type, git_commit):
            assert dataset_version == "carpedia-shadow-building"
            return self.run_id

        def persist_bronze(self, run_id, parsed):
            raw = replace(parsed.raw, asset_id=10, raw_record_id=20, pipeline_run_id=run_id)
            return replace(parsed, raw=raw), True

        def identity_candidates(self, parsed):
            return (_candidate(),)

        def persist_silver(self, run_id, specification):
            mapping = replace(specification.mapping, mapping_decision_id=30)
            return replace(specification, mapping=mapping, specification_id=40), True

        def audit_lineage(self, specifications, snapshots):
            return {
                "coherent": True,
                "specifications": len(specifications),
                "snapshots": len(snapshots),
                "publishable_snapshots": len(snapshots),
                "issue_codes": (),
            }

        def publish_shadow(self, run_id, **values):
            assert len(values["specifications"]) == len(values["snapshots"]) == 1
            assert all(item.status == "passed" for item in values["quality_results"])
            return "carpedia-shadow-v1-test", False

        def finish_run(self, run_id, status, **counts):
            self.finished = (status, counts)

    loader = MemoryLoader()
    result = run_carpedia_pipeline(
        loader,
        StaticClient(),
        CarpediaExecutionOptions(targets=(CarpediaTarget(12345, 2021),)),
    )
    assert result.status == "succeeded"
    assert result.matched == result.snapshots_published == 1
    assert result.ambiguous == result.rejected == result.not_found == result.pending == 0
    assert loader.finished[0] == "succeeded"


def test_client_stops_on_rate_limit_without_retry_or_secret_exposure():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers.get("Authorization") == f"Bearer {API_KEY}"
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = CarpediaApiClient(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
        policy=CarpediaDownloadPolicy(attempts=2, backoff_seconds=0),
        sleep=lambda _: None,
    )
    request = CarpediaRequest(
        "vehicle_specification",
        "/api/v1/ficha/12345/2021",
        external_vehicle_id=12345,
    )
    with tempfile.TemporaryDirectory() as temporary:
        with pytest.raises(RuntimeError, match="non-success status") as error:
            client.fetch(request, destination_directory=Path(temporary))
    assert API_KEY not in str(error.value)
    assert len(calls) == 1


def test_client_retries_timeout_without_exposing_secret():
    calls = 0
    delays = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("private diagnostic", request=request)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(_payload()).encode(),
        )

    client = CarpediaApiClient(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
        policy=CarpediaDownloadPolicy(attempts=2, backoff_seconds=Decimal("0.25")),
        sleep=delays.append,
    )
    with tempfile.TemporaryDirectory() as temporary:
        client.fetch(
            CarpediaRequest("vehicle_specification", "/api/v1/ficha/12345/2021"),
            destination_directory=Path(temporary),
        )
    assert calls == 2
    assert delays == [Decimal("0.25")]


def test_client_paginates_until_official_total_pages():
    pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["pagina"])
        pages.append(page)
        payload = {
            "marcas": [{"id": page, "nome": f"Marca {page}"}],
            "paginacao": {"totalPaginas": 2},
        }
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(payload).encode(),
        )

    client = CarpediaApiClient(api_key=API_KEY, transport=httpx.MockTransport(handler))
    request = CarpediaRequest("brands", "/api/v1/marcas", parameters={"pagina": 1})
    with tempfile.TemporaryDirectory() as temporary:
        assets = client.fetch_paginated(
            request,
            collection_key="marcas",
            destination_directory=Path(temporary),
        )
    assert pages == [1, 2]
    assert len(assets) == 2


def test_parser_rejects_synthetic_or_mismatched_external_identity(tmp_path):
    synthetic = _payload()
    synthetic["versao"]["id"] = 0
    with pytest.raises(ValueError, match="non-official"):
        CarpediaJsonParser().parse(_asset(tmp_path / "synthetic.json", synthetic))

    mismatched = _payload()
    mismatched["versao"]["id"] = 54321
    with pytest.raises(ValueError, match="differs"):
        CarpediaJsonParser().parse(_asset(tmp_path / "mismatch.json", mismatched))


@pytest.mark.parametrize(
    ("headers", "body", "message"),
    [
        ({"Content-Type": "text/html"}, b"{}", "content type"),
        ({"Content-Type": "application/json", "Content-Length": "99"}, b"{}", "size limit"),
        ({"Content-Type": "application/json"}, b"0123456789", "size limit"),
    ],
)
def test_client_rejects_contract_and_size_violations_without_partial_file(headers, body, message):
    client = CarpediaApiClient(
        api_key=API_KEY,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, headers=headers, content=body)),
        policy=CarpediaDownloadPolicy(attempts=1, max_response_bytes=8),
    )
    request = CarpediaRequest("vehicle_specification", "/api/v1/ficha/12345/2021")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        with pytest.raises(ValueError, match=message):
            client.fetch(request, destination_directory=directory)
        assert list(directory.iterdir()) == []


def test_quality_requires_persisted_lineage_and_matched_snapshots(tmp_path):
    parsed = CarpediaJsonParser().parse(_asset(tmp_path / "asset.json", _payload()))
    specification = build_specification(parsed, [_candidate()])
    results = evaluate_quality((specification,), ())
    failed = {item.rule_code for item in results if item.status == "failed"}
    assert "CARPEDIA_IDENTITY_ELIGIBLE" in failed
    assert "CARPEDIA_LINEAGE_COMPLETE" in failed
    assert all(isinstance(value, Decimal) for value in (Decimal("1"),))


class _PersistConnection:
    def __init__(self, prior_mapping, prior_specification, *, mapping_id=31, specification_id=41):
        self.prior_mapping = prior_mapping
        self.prior_specification = prior_specification
        self.mapping_id = mapping_id
        self.specification_id = specification_id
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters or {}))
        if "FROM silver.carpedia_vehicle_mapping_current" in sql:
            return _Result(row=self.prior_mapping)
        if "INSERT INTO silver.carpedia_vehicle_mapping" in sql:
            return _Result(scalar=self.mapping_id)
        if "FROM silver.carpedia_vehicle_specification_current" in sql:
            return _Result(row=self.prior_specification)
        if "INSERT INTO silver.carpedia_vehicle_specification" in sql:
            return _Result(scalar=self.specification_id)
        return _Result()


def test_persist_silver_reuses_only_the_same_mapping_lineage(tmp_path):
    specification = _persistable_specification(tmp_path)
    connection = _PersistConnection(
        _mapping_row(specification),
        _specification_row(specification),
    )
    loader = CarpediaVehicleSpecsLoader(_Engine(connection))

    persisted, inserted = loader.persist_silver(uuid4(), specification)

    assert inserted is False
    assert persisted.mapping.mapping_decision_id == 30
    assert persisted.specification_id == 40
    assert not any("INSERT INTO silver.carpedia_vehicle_" in sql for sql, _ in connection.calls)


@pytest.mark.parametrize(
    ("new_vehicle_sk", "prior_matcher_version"),
    [(77, "carpedia-exact-identity-previous"), (88, CARPEDIA_MATCHER_VERSION)],
)
def test_persist_silver_preserves_history_for_new_decision_or_vehicle(
    tmp_path,
    new_vehicle_sk,
    prior_matcher_version,
):
    old_specification = _persistable_specification(tmp_path, vehicle_sk=77)
    new_specification = (
        old_specification
        if new_vehicle_sk == 77
        else _persistable_specification(tmp_path, vehicle_sk=new_vehicle_sk)
    )
    # Reproduz explicitamente a condição defensiva: atributos/fingerprint iguais,
    # mas decisão ou identidade persistida diferente.
    new_specification = replace(
        new_specification,
        normalized_fingerprint=old_specification.normalized_fingerprint,
    )
    connection = _PersistConnection(
        _mapping_row(
            old_specification,
            matcher_version=prior_matcher_version,
        ),
        _specification_row(old_specification),
    )
    loader = CarpediaVehicleSpecsLoader(_Engine(connection))

    persisted, inserted = loader.persist_silver(uuid4(), new_specification)

    assert inserted is True
    assert persisted.mapping.mapping_decision_id == 31
    assert persisted.specification_id == 41
    assert persisted.supersedes_specification_id == 40
    specification_insert = next(
        parameters
        for sql, parameters in connection.calls
        if "INSERT INTO silver.carpedia_vehicle_specification" in sql
    )
    assert specification_insert["mapping"] == 31
    assert specification_insert["vehicle"] == new_vehicle_sk
    assert specification_insert["supersedes"] == 40
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "DELETE")) for sql, _ in connection.calls)


class _LineageConnection:
    def __init__(self, row):
        self.row = row

    def execute(self, statement, parameters=None):
        return _Result(row=self.row)


def _lineage_row(*, vehicle_sk=77, mapping_status="matched", current=True):
    return {
        "specification_id": 40,
        "specification_raw_record_id": 20,
        "specification_mapping_decision_id": 30,
        "specification_vehicle_sk": vehicle_sk,
        "specification_mapping_status": mapping_status,
        "mapping_decision_id": 30,
        "mapping_raw_record_id": 20,
        "mapping_vehicle_sk": vehicle_sk,
        "mapping_status": mapping_status,
        "confidence": Decimal("100") if mapping_status == "matched" else None,
        "review_required": mapping_status != "matched",
        "specification_current": current,
        "mapping_current": current,
    }


@pytest.mark.parametrize(
    ("row", "issue"),
    [
        (_lineage_row(current=False), "superseded_lineage"),
        (_lineage_row(vehicle_sk=88), "persisted_identity_mismatch"),
        (_lineage_row(vehicle_sk=None, mapping_status="rejected"), "persisted_identity_mismatch"),
        (_lineage_row(vehicle_sk=None, mapping_status="invalid"), "invalid_mapping_decision"),
    ],
)
def test_lineage_audit_blocks_superseded_invalid_or_divergent_decisions(tmp_path, row, issue):
    specification = _persistable_specification(
        tmp_path,
        mapping_id=30,
        specification_id=40,
    )
    snapshots = build_snapshots((specification,))

    evidence = CarpediaVehicleSpecsLoader._audit_lineage_with_connection(
        _LineageConnection(row),
        (specification,),
        snapshots,
    )
    results = evaluate_quality(
        (specification,),
        snapshots,
        lineage_evidence=evidence,
    )

    assert evidence["coherent"] is False
    assert issue in evidence["issue_codes"]
    assert next(
        item.status
        for item in results
        if item.rule_code == "CARPEDIA_LINEAGE_IDENTITY_COHERENT"
    ) == "failed"
    with pytest.raises(ValueError, match="hard gates"):
        require_hard_gates(results)


def test_lineage_audit_accepts_current_publishable_identity(tmp_path):
    specification = _persistable_specification(
        tmp_path,
        mapping_id=30,
        specification_id=40,
    )
    snapshots = build_snapshots((specification,))
    evidence = CarpediaVehicleSpecsLoader._audit_lineage_with_connection(
        _LineageConnection(_lineage_row()),
        (specification,),
        snapshots,
    )

    assert evidence == {
        "coherent": True,
        "specifications": 1,
        "snapshots": 1,
        "publishable_snapshots": 1,
        "issue_codes": (),
    }
    assert _mapping_decision_is_publishable("matched", 77, Decimal("100"), False)
    assert not _mapping_decision_is_publishable("rejected", None, None, True)


class _RollbackConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters or {}))
        if "WHERE is_active_shadow FOR UPDATE" in sql:
            return _Result(scalar="carpedia-shadow-current")
        if "SELECT status FROM gold.carpedia_vehicle_spec_dataset" in sql:
            return _Result(scalar="retired")
        return _Result()


def test_rollback_preserves_datasets_and_records_historical_event():
    connection = _RollbackConnection()
    loader = CarpediaVehicleSpecsLoader(_Engine(connection))

    loader.rollback_shadow(uuid4(), "carpedia-shadow-target", "controlled rollback")

    statements = [sql.strip().upper() for sql, _ in connection.calls]
    assert sum(statement.startswith("UPDATE GOLD.CARPEDIA_VEHICLE_SPEC_DATASET") for statement in statements) == 2
    assert any("INSERT INTO GOLD.CARPEDIA_VEHICLE_SPEC_DATASET_EVENT" in statement for statement in statements)
    assert not any(statement.startswith("DELETE") for statement in statements)
