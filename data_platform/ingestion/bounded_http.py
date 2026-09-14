"""Bounded, auditable HTTP collection with immutable external cache receipts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx


STOP_STATUSES = frozenset({401, 403, 429})
RATE_LIMIT_HEADERS = frozenset(
    {"retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"}
)


class AttemptLimitExceeded(RuntimeError):
    pass


class SourceStopped(RuntimeError):
    def __init__(self, provider: str, status_code: int):
        super().__init__(f"{provider} collection stopped by HTTP {status_code}")
        self.provider = provider
        self.status_code = status_code


class CollectionResponseError(RuntimeError):
    pass


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def sanitized_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        raise ValueError("Authenticated URLs are forbidden")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Absolute HTTP(S) endpoint required")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class CachedAsset:
    body: bytes
    sha256: str
    receipt_path: Path
    cache_hit: bool
    status_code: int


class PersistentAttemptLedger:
    """Reserve before I/O so an interrupted HTTP attempt is still counted."""

    def __init__(self, path: Path, *, provider: str, run_id: str, limit: int):
        if not provider.strip() or not run_id.strip():
            raise ValueError("Provider and run id are required")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Attempt limit must be a positive integer")
        self.path = Path(path).resolve()
        self.provider = provider
        self.run_id = run_id
        self.limit = limit
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            expected = (provider, run_id, limit)
            actual = (
                self._data.get("provider"),
                self._data.get("run_id"),
                self._data.get("limit"),
            )
            if actual != expected or not isinstance(self._data.get("attempts"), list):
                raise ValueError("Attempt ledger identity mismatch")
        else:
            self._data = {
                "version": "bounded-http-attempt-ledger-v1",
                "provider": provider,
                "run_id": run_id,
                "limit": limit,
                "attempts": [],
            }
            _atomic_json(self.path, self._data)

    @property
    def used(self) -> int:
        return len(self._data["attempts"])

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def reserve(self, *, endpoint: str, purpose: str, vehicle_id: int | None) -> int:
        if self.used >= self.limit:
            raise AttemptLimitExceeded(f"{self.provider} attempt limit reached")
        sequence = self.used + 1
        self._data["attempts"].append(
            {
                "sequence": sequence,
                "started_at": _timestamp(),
                "endpoint": sanitized_endpoint(endpoint),
                "purpose": purpose,
                "vehicle_id": vehicle_id,
                "cache": "miss",
                "status_code": None,
                "response_sha256": None,
                "rate_limit_headers": {},
                "outcome": "reserved",
            }
        )
        _atomic_json(self.path, self._data)
        return sequence

    def complete(
        self,
        sequence: int,
        *,
        status_code: int | None,
        response_sha256: str | None,
        rate_limit_headers: Mapping[str, str] | None = None,
        outcome: str,
    ) -> None:
        if sequence <= 0 or sequence > self.used:
            raise ValueError("Attempt sequence is outside this ledger")
        record = self._data["attempts"][sequence - 1]
        if record["sequence"] != sequence or record["outcome"] != "reserved":
            raise ValueError("Attempt was already completed or ledger is inconsistent")
        record.update(
            completed_at=_timestamp(),
            status_code=status_code,
            response_sha256=response_sha256,
            rate_limit_headers={
                key.casefold(): str(value)
                for key, value in (rate_limit_headers or {}).items()
                if key.casefold() in RATE_LIMIT_HEADERS
            },
            outcome=outcome,
        )
        _atomic_json(self.path, self._data)

    def snapshot(self) -> Mapping[str, object]:
        return json.loads(json.dumps(self._data))


class BoundedCachedHttpCollector:
    def __init__(self, *, client: httpx.Client, ledger: PersistentAttemptLedger, cache_directory: Path):
        self.client = client
        self.ledger = ledger
        self.cache_directory = Path(cache_directory).resolve()
        self.cache_directory.mkdir(parents=True, exist_ok=True)

    def _paths(self, cache_key: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self.cache_directory / f"{digest}.json", self.cache_directory / f"{digest}.receipt.json"

    def _cached(self, cache_key: str) -> CachedAsset | None:
        asset_path, receipt_path = self._paths(cache_key)
        if not asset_path.exists() and not receipt_path.exists():
            return None
        if not asset_path.is_file() or not receipt_path.is_file():
            raise CollectionResponseError("Incomplete cache entry")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        body = asset_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if (
            receipt.get("version") != "bounded-http-cache-receipt-v1"
            or receipt.get("provider") != self.ledger.provider
            or receipt.get("cache_key") != cache_key
            or receipt.get("sha256") != digest
            or receipt.get("status_code") != 200
        ):
            raise CollectionResponseError("Cached response receipt is invalid")
        return CachedAsset(body, digest, receipt_path, True, 200)

    def get(
        self,
        endpoint: str,
        *,
        cache_key: str,
        purpose: str,
        vehicle_id: int | None,
        validate: Callable[[bytes], None],
    ) -> CachedAsset:
        cached = self._cached(cache_key)
        if cached is not None:
            validate(cached.body)
            return cached
        sequence = self.ledger.reserve(endpoint=endpoint, purpose=purpose, vehicle_id=vehicle_id)
        try:
            response = self.client.get(endpoint)
        except Exception:
            self.ledger.complete(
                sequence,
                status_code=None,
                response_sha256=None,
                outcome="transport_error",
            )
            raise
        digest = hashlib.sha256(response.content).hexdigest()
        headers = {key: value for key, value in response.headers.items() if key.casefold() in RATE_LIMIT_HEADERS}
        if response.status_code in STOP_STATUSES:
            self.ledger.complete(
                sequence,
                status_code=response.status_code,
                response_sha256=digest,
                rate_limit_headers=headers,
                outcome="stopped",
            )
            raise SourceStopped(self.ledger.provider, response.status_code)
        if response.status_code != 200:
            self.ledger.complete(
                sequence,
                status_code=response.status_code,
                response_sha256=digest,
                rate_limit_headers=headers,
                outcome="http_error",
            )
            raise CollectionResponseError(
                f"{self.ledger.provider} returned HTTP {response.status_code}"
            )
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        if content_type != "application/json":
            self.ledger.complete(
                sequence,
                status_code=response.status_code,
                response_sha256=digest,
                rate_limit_headers=headers,
                outcome="incompatible_contract",
            )
            raise CollectionResponseError("Provider response contract is incompatible")
        try:
            validate(response.content)
        except Exception as exc:
            self.ledger.complete(
                sequence,
                status_code=response.status_code,
                response_sha256=digest,
                rate_limit_headers=headers,
                outcome="incompatible_contract",
            )
            raise CollectionResponseError("Provider response contract is incompatible") from exc
        self.ledger.complete(
            sequence,
            status_code=response.status_code,
            response_sha256=digest,
            rate_limit_headers=headers,
            outcome="received",
        )
        asset_path, receipt_path = self._paths(cache_key)
        if asset_path.exists() or receipt_path.exists():
            raise CollectionResponseError("Cache target appeared during collection")
        temporary_asset = asset_path.with_suffix(".json.tmp")
        temporary_asset.write_bytes(response.content)
        os.replace(temporary_asset, asset_path)
        _atomic_json(
            receipt_path,
            {
                "version": "bounded-http-cache-receipt-v1",
                "provider": self.ledger.provider,
                "cache_key": cache_key,
                "endpoint": sanitized_endpoint(endpoint),
                "status_code": 200,
                "sha256": digest,
                "collected_at": _timestamp(),
                "attempt_sequence": sequence,
            },
        )
        return CachedAsset(response.content, digest, receipt_path, False, 200)
