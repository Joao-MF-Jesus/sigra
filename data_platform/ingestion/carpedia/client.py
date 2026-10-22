from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_OFFICIAL_BASE_URL,
    CarpediaRequest,
    DownloadedCarpediaAsset,
)


CARPEDIA_ALLOWED_HOSTS = frozenset({"www.carpedia.com.br"})
_JSON_CONTENT_TYPES = frozenset({"application/json"})
_RETRYABLE_STATUS = frozenset({408, 500, 502, 503, 504})
_API_KEY_PATTERN = re.compile(r"^cpk_[A-Za-z0-9_-]{16,128}$")


def _validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() not in CARPEDIA_ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Carpedia API base URL is outside the official HTTPS allowlist")
    return value.rstrip("/") + "/"


def _validate_request(request: CarpediaRequest) -> None:
    if request.logical_endpoint not in {
        "brands",
        "models",
        "versions",
        "vehicle_specification",
        "equipment",
    }:
        raise ValueError("Carpedia logical endpoint is not recognized")
    if not request.path.startswith("/api/v1/") or ".." in request.path:
        raise ValueError("Carpedia request path is outside API v1")
    if any(key.casefold() in {"authorization", "token", "api_key", "key", "secret"} for key in request.parameters):
        raise ValueError("Carpedia credentials are forbidden in request parameters")


def _validate_temp_directory(directory: Path) -> Path:
    resolved = directory.resolve(strict=True)
    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved != system_temp and system_temp not in resolved.parents:
        raise ValueError("Carpedia downloads must use the operating-system temporary directory")
    return resolved


@dataclass(frozen=True)
class CarpediaDownloadPolicy:
    attempts: int = 3
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0
    backoff_seconds: float = 0.1
    maximum_backoff_seconds: float = 60.0
    max_response_bytes: int = 8 * 1024 * 1024
    maximum_pages: int = 100

    def __post_init__(self) -> None:
        integer_fields = (self.attempts, self.max_response_bytes, self.maximum_pages)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in integer_fields):
            raise ValueError("Carpedia download limits must be positive integers")
        if any(value < 0 for value in (self.backoff_seconds, self.maximum_backoff_seconds)):
            raise ValueError("Carpedia retry backoff cannot be negative")
        if self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ValueError("Carpedia timeouts must be positive")


class CarpediaApiClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        policy: CarpediaDownloadPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        resolved_key = api_key if api_key is not None else os.getenv("CARPEDIA_API_KEY", "")
        if not _API_KEY_PATTERN.fullmatch(resolved_key.strip()):
            raise ValueError("CARPEDIA_API_KEY is missing or has an invalid format")
        self._api_key = resolved_key.strip()
        self.base_url = _validate_base_url(base_url or CARPEDIA_OFFICIAL_BASE_URL)
        self.transport = transport
        self.policy = policy or CarpediaDownloadPolicy()
        self._sleep = sleep

    def fetch(
        self,
        request: CarpediaRequest,
        *,
        destination_directory: Path,
    ) -> DownloadedCarpediaAsset:
        _validate_request(request)
        directory = _validate_temp_directory(destination_directory)
        request_key = json.dumps(
            [request.logical_endpoint, request.path, sorted(request.parameters.items())],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        stem = hashlib.sha256(request_key.encode("ascii")).hexdigest()[:20]
        partial = directory / f"carpedia-{stem}.json.part"
        final = directory / f"carpedia-{stem}.json"
        if partial.exists() or final.exists():
            raise FileExistsError("Carpedia temporary response target already exists")
        timeout = httpx.Timeout(
            connect=self.policy.connect_timeout_seconds,
            read=self.policy.read_timeout_seconds,
            write=self.policy.read_timeout_seconds,
            pool=self.policy.connect_timeout_seconds,
        )
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=timeout,
                follow_redirects=False,
                headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
            ) as client:
                for attempt in range(1, self.policy.attempts + 1):
                    delay = self.policy.backoff_seconds * (2 ** (attempt - 1))
                    try:
                        return self._fetch_once(client, request, partial, final)
                    except httpx.TimeoutException as exc:
                        if attempt == self.policy.attempts:
                            raise RuntimeError("Carpedia request timed out") from exc
                    except _RetryableResponse as exc:
                        if attempt == self.policy.attempts:
                            raise RuntimeError("Carpedia request failed after controlled retries") from exc
                        delay = exc.retry_after_seconds
                    if partial.exists():
                        partial.unlink()
                    self._sleep(min(delay, self.policy.maximum_backoff_seconds))
        except Exception:
            for path in (partial, final):
                if path.exists():
                    path.unlink()
            raise
        raise RuntimeError("Carpedia request did not produce a response")

    def _fetch_once(
        self,
        client: httpx.Client,
        request: CarpediaRequest,
        partial: Path,
        final: Path,
    ) -> DownloadedCarpediaAsset:
        from datetime import UTC, datetime

        url = urljoin(self.base_url, request.path.lstrip("/"))
        parsed = urlsplit(url)
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in CARPEDIA_ALLOWED_HOSTS:
            raise ValueError("Carpedia request resolved outside the official allowlist")
        with client.stream("GET", url, params=request.parameters) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                raise ValueError("Carpedia redirects are not accepted")
            if response.status_code in _RETRYABLE_STATUS:
                raise _RetryableResponse(
                    response.status_code,
                    _retry_after(response.headers.get("retry-after"), self.policy.backoff_seconds),
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError("Carpedia API returned a non-success status")
            media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
            if media_type not in _JSON_CONTENT_TYPES:
                raise ValueError("Carpedia API response content type is not JSON")
            announced = response.headers.get("content-length")
            if announced is not None:
                try:
                    announced_size = int(announced)
                except ValueError:
                    announced_size = None
                if announced_size is not None and (
                    announced_size < 0 or announced_size > self.policy.max_response_bytes
                ):
                    raise ValueError("Carpedia API response exceeds the configured size limit")
            digest = hashlib.sha256()
            size = 0
            with partial.open("xb") as output:
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.policy.max_response_bytes:
                        raise ValueError("Carpedia API response exceeds the configured size limit")
                    output.write(chunk)
                    digest.update(chunk)
            if not size:
                raise ValueError("Carpedia API response is empty")
            partial.replace(final)
            return DownloadedCarpediaAsset(
                request=request,
                path=final,
                collected_at=datetime.now(UTC),
                http_status=response.status_code,
                content_type=media_type,
                byte_length=size,
                sha256=digest.hexdigest(),
            )

    def fetch_paginated(
        self,
        request: CarpediaRequest,
        *,
        collection_key: str,
        destination_directory: Path,
    ) -> tuple[DownloadedCarpediaAsset, ...]:
        page = int(request.parameters.get("pagina", 1))
        assets: list[DownloadedCarpediaAsset] = []
        while True:
            page_request = CarpediaRequest(
                logical_endpoint=request.logical_endpoint,
                path=request.path,
                parameters={**request.parameters, "pagina": page},
                external_vehicle_id=request.external_vehicle_id,
                source_reference=request.source_reference,
            )
            asset = self.fetch(page_request, destination_directory=destination_directory)
            assets.append(asset)
            try:
                payload = json.loads(asset.path.read_text(encoding="utf-8"))
                pagination = payload["paginacao"]
                total_pages = int(pagination["totalPaginas"])
                if not isinstance(payload.get(collection_key), list):
                    raise ValueError
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("Carpedia paginated response contract is invalid") from exc
            if total_pages < page or total_pages > self.policy.maximum_pages:
                raise ValueError("Carpedia pagination exceeds the configured limit")
            if page >= total_pages:
                return tuple(assets)
            page += 1


def _retry_after(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, parsed)


class _RetryableResponse(RuntimeError):
    def __init__(self, status_code: int, retry_after_seconds: float) -> None:
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__("retryable Carpedia response")
