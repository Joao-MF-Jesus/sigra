from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import tempfile
from uuid import uuid4

import httpx
import pytest

from data_platform.carpedia.pipeline import CarpediaExecutionOptions, run_carpedia_pipeline
from data_platform.contracts.carpedia_vehicle_specs import (
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
from data_platform.quality.carpedia_checks import build_snapshots, evaluate_quality
from data_platform.transformation.carpedia import build_specification, normalize_text


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


def test_client_auth_hash_size_content_type_and_retry_are_controlled():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers.get("Authorization") == f"Bearer {API_KEY}"
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        body = json.dumps(_payload()).encode()
        return httpx.Response(200, headers={"Content-Type": "application/json"}, content=body)

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
        asset = client.fetch(request, destination_directory=Path(temporary))
        assert asset.byte_length == asset.path.stat().st_size
        assert len(asset.sha256) == 64
    assert len(calls) == 2


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
