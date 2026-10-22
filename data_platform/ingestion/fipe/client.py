from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx


@dataclass(frozen=True)
class FipeResponse:
    endpoint: str
    status_code: int
    body: bytes
    collected_at: datetime


class FipeHttpClient:
    def __init__(self, base_url: str, timeout_seconds: float, transport=None):
        self._client = httpx.Client(base_url=base_url, timeout=timeout_seconds, transport=transport)

    def fetch(self, endpoint: str) -> FipeResponse:
        response = self._client.get(endpoint)
        return FipeResponse(endpoint, response.status_code, response.content, datetime.now(UTC))

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
