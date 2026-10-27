from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
import time
from typing import Callable

import httpx

from data_platform.contracts.pbev import AuditedAsset
from data_platform.ingestion.pbev.parser import PbevValidationError, sanitize_official_url


@dataclass(frozen=True)
class PbevDownloadPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    connect_timeout_seconds: float = 20.0
    read_timeout_seconds: float = 120.0


class PbevAssetClient:
    """Download explicito; nenhuma chamada ocorre em dry-run ou testes padrao."""

    def __init__(
        self,
        policy: PbevDownloadPolicy | None = None,
        *,
        transport=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.policy = policy or PbevDownloadPolicy()
        self.sleep = sleep
        timeout = httpx.Timeout(
            connect=self.policy.connect_timeout_seconds,
            read=self.policy.read_timeout_seconds,
            write=self.policy.read_timeout_seconds,
            pool=self.policy.connect_timeout_seconds,
        )
        self.client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def download(self, asset: AuditedAsset, destination: Path) -> Path:
        url = sanitize_official_url(asset.download_url)
        last_error: BaseException | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                response = self.client.get(url)
                if response.status_code in {408, 429} or response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    raise PbevValidationError(f"permanent PBEV HTTP status {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                if content_type != "application/pdf" or not response.content.startswith(b"%PDF-"):
                    raise PbevValidationError("PBEV response is not a PDF")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.content)
                return destination
            except PbevValidationError:
                raise
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if status is not None and status not in {408, 429} and status < 500:
                    raise
                if attempt >= self.policy.max_attempts:
                    break
                delay = self.policy.backoff_seconds * (2 ** (attempt - 1))
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = exc.response.headers.get("retry-after")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except ValueError:
                            try:
                                delay = max(
                                    delay,
                                    (parsedate_to_datetime(retry_after) - parsedate_to_datetime(exc.response.headers["date"])).total_seconds(),
                                )
                            except Exception:
                                pass
                self.sleep(max(0.0, delay))
        raise RuntimeError("PBEV download exhausted transient retries") from last_error
