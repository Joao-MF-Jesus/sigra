from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from data_platform.common.logging import sanitize
from data_platform.contracts.fipe import FipeTarget
from data_platform.ingestion.fipe.client import FipeResponse
from data_platform.ingestion.fipe.extractor import extract_record, payload_hash, schema_fingerprint
from data_platform.ingestion.fipe.pipeline import PipelinePersistenceError, run_pipeline


TARGET = FipeTarget("car", "004517-9", "2021-1")
PAYLOAD = {"price": "R$ 80.000,00", "codeFipe": "004517-9", "modelYear": 2021, "referenceMonth": "agosto de 2026"}


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)

    def fetch(self, endpoint):
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        return FipeResponse(endpoint, status, body, datetime.now(UTC))


class FakeLoader:
    def __init__(self, inserts=None, start_error=None, insert_error=None, finish_errors=None):
        self.inserts = iter(inserts or [True] * 20)
        self.start_error = start_error
        self.insert_error = insert_error
        self.finish_errors = iter(finish_errors or [])
        self.started = []
        self.finished = []
        self.records = []

    def start_run(self, *args):
        if self.start_error:
            raise self.start_error
        self.started.append(args)

    def insert(self, *args):
        if self.insert_error:
            raise self.insert_error
        self.records.append(args[1])
        return next(self.inserts)

    def finish_run(self, *args):
        self.finished.append(args)
        error = next(self.finish_errors, None)
        if error:
            raise error


def response(payload=PAYLOAD, status=200):
    return FipeResponse(TARGET.endpoint, status, json.dumps(payload).encode(), datetime.now(UTC))


def test_hash_is_deterministic_and_key_order_independent():
    assert payload_hash({"b": 2, "a": 1}) == payload_hash({"a": 1, "b": 2})
    assert len(payload_hash(PAYLOAD)) == 64


def test_schema_fingerprint_tracks_shape_not_values():
    assert schema_fingerprint({"a": 1}) == schema_fingerprint({"a": 999})
    assert schema_fingerprint({"a": 1}) != schema_fingerprint({"b": 1})


def test_valid_payload_preserves_original_values():
    record = extract_record(response(), TARGET)
    assert record.payload == PAYLOAD
    assert record.year_code == "2021-1"
    assert record.source_record_key == "004517-9:2021-1"
    assert record.ingestion_status == "received"
    assert record.raw_content_length == len(json.dumps(PAYLOAD).encode())
    assert record.collected_at.tzinfo is UTC
    assert record.http_status == 200


def test_target_year_code_fuel_suffix_is_not_replaced_by_model_year():
    record = extract_record(response({**PAYLOAD, "modelYear": 1999}), TARGET)
    assert record.year_code == TARGET.year_code
    assert record.source_record_key.endswith(f":{TARGET.year_code}")


@pytest.mark.parametrize("status,body,expected_status", [
    (200, b"not-json password=must-not-be-stored", "invalid_json"),
    (503, b'{"token":"must-not-be-stored"}', "http_error"),
])
def test_invalid_json_and_http_error_are_persisted_as_safe_bronze_events(status, body, expected_status):
    loader = FakeLoader()
    result = run_pipeline([TARGET], FakeClient([(status, body)]), loader)
    assert result.status == "failed"
    assert result.records_rejected == 1
    assert result.records_inserted == 1
    assert len(loader.records) == 1
    event = loader.records[0]
    assert event.ingestion_status == expected_status
    assert event.payload is None
    assert event.schema_fingerprint is None
    assert event.payload_hash == hashlib.sha256(body).hexdigest()
    assert event.raw_content_length == len(body)
    assert "must-not-be-stored" not in repr(event)
    assert "must-not-be-stored" not in ";".join(result.errors)
    assert loader.finished


def test_timeout_has_no_bronze_event_because_no_response_was_received():
    loader = FakeLoader()
    result = run_pipeline([TARGET], FakeClient([httpx.ReadTimeout("timed out")]), loader)
    assert result.status == "failed"
    assert result.records_received == 0
    assert result.records_inserted == 0
    assert result.records_rejected == 1
    assert loader.records == []
    assert "timed out" in result.errors[0]


@pytest.mark.parametrize("status,body", [
    (200, b"invalid-json"),
    (503, b"upstream-error"),
])
def test_invalid_bronze_events_are_idempotent(status, body):
    first_loader = FakeLoader([True])
    second_loader = FakeLoader([False])
    first = run_pipeline([TARGET], FakeClient([(status, body)]), first_loader)
    second = run_pipeline([TARGET], FakeClient([(status, body)]), second_loader)
    assert first.status == second.status == "failed"
    assert (first.records_inserted, first.records_deduplicated) == (1, 0)
    assert (second.records_inserted, second.records_deduplicated) == (0, 1)
    assert first_loader.records[0].payload_hash == second_loader.records[0].payload_hash


def test_successful_run_and_duplicate_are_idempotent():
    first = run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), FakeLoader([True]))
    second = run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), FakeLoader([False]))
    assert first.status == second.status == "succeeded"
    assert first.records_inserted == 1
    assert second.records_deduplicated == 1


def test_partial_run_combines_success_and_failure():
    loader = FakeLoader([True, True])
    result = run_pipeline([TARGET, TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode()), (500, b'{}')]), loader)
    assert result.status == "partial"
    assert (result.records_inserted, result.records_rejected) == (2, 1)


def test_dry_run_never_calls_loader():
    result = run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), None, dry_run=True)
    assert result.status == "succeeded"
    assert result.records_validated == 1
    assert result.records_inserted == 0


def test_insert_failure_finalizes_run_as_failed_with_sanitized_error():
    loader = FakeLoader(insert_error=RuntimeError("password=super-secret"))
    result = run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), loader)
    assert result.status == "failed"
    assert result.records_inserted == 0
    assert result.records_rejected == 1
    assert loader.finished[-1][1] == "failed"
    assert "super-secret" not in loader.finished[-1][-1]


def test_finish_failure_retries_finalization_as_failed():
    loader = FakeLoader(finish_errors=[RuntimeError("token=private"), None])
    result = run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), loader)
    assert result.status == "failed"
    assert [call[1] for call in loader.finished] == ["succeeded", "failed"]
    assert "private" not in result.errors[-1]


def test_second_finish_failure_raises_only_sanitized_error():
    loader = FakeLoader(finish_errors=[RuntimeError("token=first"), RuntimeError("password=second")])
    with pytest.raises(PipelinePersistenceError) as error:
        run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), loader)
    assert "first" not in str(error.value)
    assert "second" not in str(error.value)


def test_start_failure_does_not_expose_credentials():
    loader = FakeLoader(start_error=RuntimeError("api_key=start-secret"))
    with pytest.raises(PipelinePersistenceError) as error:
        run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), loader)
    assert "start-secret" not in str(error.value)


def test_credentials_are_removed_from_errors_and_urls():
    value = sanitize("https://alice:secret@example.test/path?token=abc&api_key=xyz")
    assert "secret" not in value and "abc" not in value and "xyz" not in value
    assert "alice" not in value


def test_authenticated_endpoint_and_invalid_body_are_not_persisted():
    secret_body = b"password=body-secret"
    event = extract_record(
        FipeResponse(
            "https://alice:url-secret@example.test/fipe?token=query-secret#fragment",
            200,
            secret_body,
            datetime.now(UTC),
        ),
        TARGET,
    )
    assert event.source_endpoint == "https://example.test/fipe"
    serialized = repr(event)
    for secret in ("alice", "url-secret", "query-secret", "body-secret"):
        assert secret not in serialized
    assert event.payload is None
    assert event.payload_hash == hashlib.sha256(secret_body).hexdigest()


def test_migration_contains_critical_constraints_and_postgresql_guard():
    migration = (Path(__file__).parents[2] / "backend" / "alembic" / "versions" / "20260803_0002_data_platform_bronze.py").read_text(encoding="utf-8")
    for marker in ("uq_fipe_raw_event_content", "ck_pipeline_run_counts", "ck_pipeline_run_timestamps", "ck_fipe_raw_payload_hash", "ck_fipe_raw_payload_by_status", "raw_content_length", "schema=\"bronze\"", "if not _is_postgresql()"):
        assert marker in migration


def test_tests_do_not_use_real_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("real network forbidden")
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    result = run_pipeline([TARGET], FakeClient([(200, json.dumps(PAYLOAD).encode())]), None, dry_run=True)
    assert result.status == "succeeded"
