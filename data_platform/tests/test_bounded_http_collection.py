import json

import httpx
import pytest

from data_platform.ingestion.bounded_http import (
    AttemptLimitExceeded,
    BoundedCachedHttpCollector,
    CollectionResponseError,
    PersistentAttemptLedger,
    SourceStopped,
)


def collector(tmp_path, handler, *, limit=3, run_id="unit-run"):
    ledger = PersistentAttemptLedger(
        tmp_path / "ledger.json", provider="test-provider", run_id=run_id, limit=limit
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BoundedCachedHttpCollector(
        client=client, ledger=ledger, cache_directory=tmp_path / "cache"
    ), ledger, client


def valid_json(body):
    payload = json.loads(body)
    if payload.get("contract") != "expected":
        raise ValueError("unexpected contract")


def test_success_is_persisted_and_cache_hit_costs_zero_attempts(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json={"contract": "expected"}, request=request)

    instance, ledger, client = collector(tmp_path, handler)
    try:
        first = instance.get(
            "https://example.test/api/item/1?ignored=secret",
            cache_key="item:1:v1",
            purpose="fixture",
            vehicle_id=1,
            validate=valid_json,
        )
        second = instance.get(
            "https://example.test/api/item/1?ignored=secret",
            cache_key="item:1:v1",
            purpose="fixture",
            vehicle_id=1,
            validate=valid_json,
        )
    finally:
        client.close()
    assert not first.cache_hit and second.cache_hit and len(calls) == 1
    assert ledger.used == 1 and ledger.remaining == 2
    saved = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert saved["attempts"][0]["endpoint"] == "https://example.test/api/item/1"
    assert "secret" not in json.dumps(saved)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_auth_and_rate_limit_status_stop_without_retry(tmp_path, status):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "blocked"}, request=request)

    instance, ledger, client = collector(tmp_path, handler)
    try:
        with pytest.raises(SourceStopped) as error:
            instance.get(
                "https://example.test/api/item/1",
                cache_key=f"item:{status}",
                purpose="fixture",
                vehicle_id=1,
                validate=valid_json,
            )
    finally:
        client.close()
    assert error.value.status_code == status and calls == 1 and ledger.used == 1


def test_limit_is_checked_before_transport_and_survives_reload(tmp_path):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"error": "missing"}, request=request)

    instance, ledger, client = collector(tmp_path, handler, limit=1)
    try:
        with pytest.raises(CollectionResponseError):
            instance.get(
                "https://example.test/api/first",
                cache_key="first",
                purpose="fixture",
                vehicle_id=1,
                validate=valid_json,
            )
        with pytest.raises(AttemptLimitExceeded):
            instance.get(
                "https://example.test/api/second",
                cache_key="second",
                purpose="fixture",
                vehicle_id=2,
                validate=valid_json,
            )
    finally:
        client.close()
    restored = PersistentAttemptLedger(
        tmp_path / "ledger.json", provider="test-provider", run_id="unit-run", limit=1
    )
    assert calls == 1 and ledger.used == restored.used == 1


def test_incompatible_contract_counts_attempt_and_writes_no_cache(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"contract": "changed"}, request=request)

    instance, ledger, client = collector(tmp_path, handler)
    try:
        with pytest.raises(CollectionResponseError, match="contract is incompatible"):
            instance.get(
                "https://example.test/api/item/1",
                cache_key="changed",
                purpose="fixture",
                vehicle_id=1,
                validate=valid_json,
            )
    finally:
        client.close()
    snapshot = ledger.snapshot()
    assert ledger.used == 1 and not list((tmp_path / "cache").glob("*.receipt.json"))
    assert snapshot["attempts"][0]["outcome"] == "incompatible_contract"


def test_ledger_rejects_identity_change_and_authenticated_url(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = PersistentAttemptLedger(path, provider="provider-a", run_id="run-a", limit=2)
    with pytest.raises(ValueError, match="Authenticated URLs"):
        ledger.reserve(endpoint="https://user:password@example.test/api", purpose="fixture", vehicle_id=1)
    with pytest.raises(ValueError, match="identity mismatch"):
        PersistentAttemptLedger(path, provider="provider-b", run_id="run-a", limit=2)
