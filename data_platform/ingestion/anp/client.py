from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tempfile
import time
from urllib.parse import urljoin, urlsplit

import httpx

from data_platform.anp.sources import ANP_ALLOWED_HOSTS
from data_platform.common.logging import sanitize_endpoint
from data_platform.contracts.anp_fuel_prices import DownloadedAnpAsset


_RETRYABLE_STATUS = frozenset({408, 429})
_CSV_CONTENT_TYPES = frozenset({"text/csv", "application/csv"})


def _validate_official_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in ANP_ALLOWED_HOSTS:
        raise ValueError("ANP download endpoint is outside the HTTPS allowlist")
    if parsed.username or parsed.password:
        raise ValueError("authenticated ANP download endpoints are forbidden")


def _validate_temp_directory(directory: Path) -> Path:
    resolved = directory.resolve(strict=True)
    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved != system_temp and system_temp not in resolved.parents:
        raise ValueError("ANP downloads must use the operating-system temporary directory")
    return resolved


@dataclass(frozen=True)
class AnpDownloadPolicy:
    attempts: int = 3
    connect_timeout_seconds: float = 20.0
    read_timeout_seconds: float = 120.0
    retry_delay_seconds: float = 0.05
    max_asset_bytes: int = 32 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_asset_bytes, bool)
            or not isinstance(self.max_asset_bytes, int)
            or self.max_asset_bytes <= 0
        ):
            raise ValueError("ANP maximum asset size must be a positive integer")


class AnpCsvClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        policy: AnpDownloadPolicy | None = None,
    ) -> None:
        self.transport = transport
        self.policy = policy or AnpDownloadPolicy()

    def download(
        self,
        *,
        source_reference: str,
        official_page_url: str,
        download_url: str,
        filename: str,
        destination_directory: Path,
    ) -> DownloadedAnpAsset:
        _validate_official_url(official_page_url)
        _validate_official_url(download_url)
        destination = _validate_temp_directory(destination_directory) / filename
        if destination.exists():
            raise FileExistsError("ANP temporary download target already exists")
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
            ) as client:
                for attempt in range(1, self.policy.attempts + 1):
                    try:
                        result = self._download_once(
                            client,
                            download_url,
                            destination,
                            source_reference,
                            official_page_url,
                            filename,
                        )
                        return result
                    except httpx.TimeoutException as exc:
                        if attempt == self.policy.attempts:
                            raise RuntimeError("ANP download timed out") from exc
                    except _RetryableResponse as exc:
                        if attempt == self.policy.attempts:
                            raise RuntimeError("ANP download failed after controlled retries") from exc
                    if destination.exists():
                        destination.unlink()
                    time.sleep(self.policy.retry_delay_seconds)
        except Exception:
            if destination.exists():
                destination.unlink()
            raise
        raise RuntimeError("ANP download did not produce an asset")

    def _download_once(
        self,
        client: httpx.Client,
        initial_url: str,
        destination: Path,
        source_reference: str,
        official_page_url: str,
        filename: str,
    ) -> DownloadedAnpAsset:
        current_url = initial_url
        redirects = 0
        while True:
            _validate_official_url(current_url)
            with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirects >= 5:
                        raise ValueError("invalid ANP redirect chain")
                    current_url = urljoin(current_url, location)
                    redirects += 1
                    continue
                if response.status_code in _RETRYABLE_STATUS or response.status_code >= 500:
                    raise _RetryableResponse(response.status_code)
                if response.status_code < 200 or response.status_code >= 300:
                    raise RuntimeError("ANP download returned a non-success status")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                if media_type not in _CSV_CONTENT_TYPES:
                    raise ValueError("ANP download content type is not CSV")
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        announced_size = int(content_length)
                    except ValueError:
                        announced_size = None
                    if (
                        announced_size is not None
                        and announced_size > self.policy.max_asset_bytes
                    ):
                        raise ValueError("ANP download exceeds the configured asset size limit")
                digest = hashlib.sha256()
                size = 0
                prefix = bytearray()
                with destination.open("xb") as output:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > self.policy.max_asset_bytes:
                            raise ValueError("ANP download exceeds the configured asset size limit")
                        if len(prefix) < 512:
                            prefix.extend(chunk[: 512 - len(prefix)])
                        output.write(chunk)
                        digest.update(chunk)
                probe = bytes(prefix).lstrip(b"\xef\xbb\xbf \t\r\n").lower()
                if not size or probe.startswith((b"<!doctype html", b"<html")):
                    raise ValueError("ANP download content is empty or HTML, not CSV")
                return DownloadedAnpAsset(
                    source_reference=source_reference,
                    official_page_url=sanitize_endpoint(official_page_url),
                    download_url_sanitized=sanitize_endpoint(current_url),
                    filename=filename,
                    path=destination,
                    collected_at=datetime.now(UTC),
                    http_status=response.status_code,
                    content_type=media_type,
                    byte_length=size,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    sha256=digest.hexdigest(),
                )


class _RetryableResponse(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"retryable ANP response status {status_code}")
