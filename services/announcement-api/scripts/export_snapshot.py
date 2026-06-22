from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

import requests

SERVICE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVICE_ROOT.parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.direct.collectors import DirectAnnouncementSource  # noqa: E402


PUBLIC_ORGANIZATIONS = {"LH", "SH", "GH"}
REQUIRED_FIELDS = {"id", "source_id", "title", "organization", "announcement_url"}


def _read_existing(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    announcements = payload.get("announcements", []) if isinstance(payload, dict) else []
    if not isinstance(announcements, list):
        raise ValueError("기존 실공고 스냅샷의 announcements 형식이 올바르지 않습니다.")
    return [item for item in announcements if isinstance(item, dict)]


def _fetch_direct(days_back: int) -> tuple[list[dict[str, Any]], list[str], str]:
    api_key = os.getenv("DATA_GO_KR_API_KEY", "").strip()
    if not api_key:
        raise ValueError("DATA_GO_KR_API_KEY가 없어 GitHub 직접 수집을 시작할 수 없습니다.")
    source = DirectAnnouncementSource(
        api_key=api_key,
        timeout_seconds=180,
        cache_ttl_seconds=60,
        include_private_housing=False,
    )
    announcements = source.fetch(days_back=days_back, force_refresh=True)
    return [item.to_dict() for item in announcements], source.errors, "github_actions_direct"


def _fetch_from_api(
    base_url: str, days_back: int, sync_token: str
) -> tuple[list[dict[str, Any]], list[str], str]:
    base_url = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if sync_token:
        headers["X-Sync-Token"] = sync_token
    sync = requests.post(
        f"{base_url}/v1/announcements/sync",
        headers=headers,
        json={"full": days_back >= 90, "days_back": days_back},
        timeout=300,
    )
    sync.raise_for_status()
    sync_payload = sync.json()
    response = requests.get(f"{base_url}/v1/announcements", timeout=300)
    response.raise_for_status()
    payload = response.json()
    announcements = payload.get("announcements", [])
    if not isinstance(announcements, list):
        raise ValueError("공고 API 응답의 announcements 형식이 올바르지 않습니다.")
    warnings = sync_payload.get("collector_warnings", [])
    return announcements, warnings if isinstance(warnings, list) else [], "render_api_export"


def _validate(items: list[dict[str, Any]], minimum_count: int) -> None:
    if len(items) < minimum_count:
        raise ValueError(f"검증된 공공주택 공고가 {len(items)}건으로 최소 {minimum_count}건보다 적습니다.")
    ids: set[str] = set()
    for item in items:
        missing = [field for field in REQUIRED_FIELDS if not str(item.get(field) or "").strip()]
        if missing:
            raise ValueError(f"필수 필드가 없는 공고가 있습니다: {item.get('id')} / {missing}")
        if item["organization"] not in PUBLIC_ORGANIZATIONS:
            raise ValueError(f"공공주택 범위 밖 기관이 포함됐습니다: {item['organization']}")
        source_id = str(item["source_id"])
        if source_id in ids:
            raise ValueError(f"중복 source_id가 있습니다: {source_id}")
        ids.add(source_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "live_housing_programs.json",
    )
    parser.add_argument("--days-back", type=int, default=7)
    parser.add_argument("--minimum-count", type=int, default=10)
    parser.add_argument("--api-url", default=os.getenv("ANNOUNCEMENT_API_BASE_URL", ""))
    args = parser.parse_args()

    days_back = max(1, min(args.days_back, 365))
    existing = _read_existing(args.output)
    api_key = os.getenv("DATA_GO_KR_API_KEY", "").strip()
    if api_key:
        fetched, warnings, source = _fetch_direct(days_back)
    elif args.api_url:
        fetched, warnings, source = _fetch_from_api(
            args.api_url,
            days_back,
            os.getenv("ANNOUNCEMENT_SYNC_TOKEN", "").strip(),
        )
    else:
        raise ValueError("직접 수집 키와 대체 공고 API 주소가 모두 없습니다.")

    merged = {
        str(item.get("source_id")): item
        for item in existing
        if item.get("source_id") and item.get("organization") in PUBLIC_ORGANIZATIONS
    }
    for item in fetched:
        if item.get("source_id") and item.get("organization") in PUBLIC_ORGANIZATIONS:
            merged[str(item["source_id"])] = item
    announcements = sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("apply_end") or ""),
            str(item.get("metadata", {}).get("notice_date") or ""),
            str(item.get("source_id") or ""),
        ),
        reverse=True,
    )
    _validate(announcements, args.minimum_count)

    generated_at = datetime.now(timezone.utc).isoformat()
    output = {
        "schema_version": 1,
        "generated_at": generated_at,
        "source": source,
        "count": len(announcements),
        "collector_warnings": warnings,
        "announcements": announcements,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "status": "ok",
                "source": source,
                "fetched": len(fetched),
                "stored": len(announcements),
                "generated_at": generated_at,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
