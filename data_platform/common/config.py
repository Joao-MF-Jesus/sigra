from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DataPlatformSettings:
    database_url: str
    fipe_api_url: str = "https://fipe.parallelum.com.br/api/v2"
    timeout_seconds: float = 10.0


def load_settings() -> DataPlatformSettings:
    return DataPlatformSettings(
        database_url=os.getenv("DATA_PLATFORM_DATABASE_URL", "").strip(),
        fipe_api_url=os.getenv("DATA_PLATFORM_FIPE_API_URL", "https://fipe.parallelum.com.br/api/v2").rstrip("/"),
        timeout_seconds=max(0.1, float(os.getenv("DATA_PLATFORM_HTTP_TIMEOUT_SECONDS", "10"))),
    )
