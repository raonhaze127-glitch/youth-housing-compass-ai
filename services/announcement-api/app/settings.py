from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    source: str
    k_apt_alert_api_base_url: str
    sample_data_path: Path
    timeout_seconds: int
    database_path: Path
    data_go_kr_api_key: str
    direct_cache_ttl_seconds: int
    direct_sync_interval_seconds: int
    sync_token: str


def load_settings() -> Settings:
    service_root = Path(__file__).resolve().parents[1]
    load_dotenv(service_root / ".env.local", override=False)
    default_sample = Path(__file__).resolve().parents[3] / "data" / "housing_programs.json"
    return Settings(
        source=os.getenv("ANNOUNCEMENT_SOURCE", "sample").strip().lower(),
        k_apt_alert_api_base_url=os.getenv("K_APT_ALERT_API_BASE_URL", "").strip().rstrip("/"),
        sample_data_path=Path(os.getenv("SAMPLE_DATA_PATH", str(default_sample))),
        timeout_seconds=max(1, int(os.getenv("SOURCE_TIMEOUT_SECONDS", "180"))),
        database_path=Path(
            os.getenv(
                "ANNOUNCEMENT_DATABASE_PATH",
                str(Path(__file__).resolve().parents[1] / ".local" / "compass.db"),
            )
        ),
        data_go_kr_api_key=os.getenv("DATA_GO_KR_API_KEY", "").strip(),
        direct_cache_ttl_seconds=max(60, int(os.getenv("DIRECT_CACHE_TTL_SECONDS", "900"))),
        direct_sync_interval_seconds=max(
            3600, int(os.getenv("DIRECT_SYNC_INTERVAL_SECONDS", "86400"))
        ),
        sync_token=os.getenv("ANNOUNCEMENT_SYNC_TOKEN", "").strip(),
    )
