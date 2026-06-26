from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "live_housing_programs.json"
DEFAULT_DATABASE_ID = "a0cdb11747fd41698ee53dc8f6a86e9f"
NOTION_VERSION = "2022-06-28"
KST = timezone(timedelta(hours=9))


def _collected_date_from_generated_at(value: str) -> str:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(KST).date().isoformat()
        except ValueError:
            return value[:10]
    return datetime.now(KST).date().isoformat()

STATUS_LABELS = {
    "open": "진행 중",
    "planned": "시작 전",
    "closed": "완료",
    "unknown": "시작 전",
}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip() or default


def _clean(value: Any, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    if limit and len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _date(value: Any) -> dict[str, Any] | None:
    text = _clean(value)
    if not text:
        return None
    return {"date": {"start": text[:10]}}


def _rich_text(value: Any, limit: int = 1800) -> dict[str, Any]:
    text = _clean(value, limit)
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def _title(value: Any) -> dict[str, Any]:
    text = _clean(value, 1800) or "제목 없음"
    return {"title": [{"text": {"content": text}}]}


def _select(value: Any) -> dict[str, Any] | None:
    text = _clean(value)
    return {"select": {"name": text}} if text else None


def _status(value: Any) -> dict[str, Any]:
    text = STATUS_LABELS.get(_clean(value), "시작 전")
    return {"status": {"name": text}}


def _notice_type(item: dict[str, Any]) -> str:
    text = " ".join(
        _clean(item.get(key)).lower()
        for key in ("housing_type", "category", "title")
    )
    if "분양" in text or "sale" in text:
        return "public_sale"
    if text:
        return "public_rent"
    return "unknown"


def _metadata_date(item: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for key in keys:
        value = metadata.get(key) or item.get(key)
        date_value = _date(value)
        if date_value:
            return date_value
    return None


def _item_properties(item: dict[str, Any], collected_date: str) -> dict[str, Any]:
    source_id = _clean(item.get("source_id") or item.get("id"))
    properties: dict[str, Any] = {
        "제목": _title(item.get("title")),
        "지역": _rich_text(item.get("region")),
        "source_category": _rich_text(item.get("category")),
        "housing_program": _rich_text(item.get("housing_type")),
        "dedup_key": _rich_text(source_id),
        "notice_type": {"select": {"name": _notice_type(item)}},
        "raw_status": _status(item.get("status")),
        "처리상태": {"status": {"name": "시작 전"}},
        "수집일": {"date": {"start": collected_date}},
    }
    organization = _select(item.get("organization"))
    if organization:
        properties["청약"] = organization
    url = _clean(item.get("announcement_url"))
    if url:
        properties["원문URL"] = {"url": url}
    apply_start = _date(item.get("apply_start"))
    if apply_start:
        properties["청약시작일"] = apply_start
    apply_end = _date(item.get("apply_end"))
    if apply_end:
        properties["청약마감일"] = apply_end
    notice_date = _metadata_date(item, "notice_date", "posted_date", "announcement_date")
    if notice_date:
        properties["공고일"] = notice_date
    created_date = _metadata_date(item, "created_date", "written_date", "notice_date", "posted_date", "announcement_date")
    if created_date:
        properties["작성일"] = created_date
    return properties




def _property_text(properties: dict[str, Any], name: str) -> str:
    value = properties.get(name) or {}
    if value.get("type") == "rich_text":
        return "".join(part.get("plain_text", "") for part in value.get("rich_text") or [])
    if value.get("type") == "title":
        return "".join(part.get("plain_text", "") for part in value.get("title") or [])
    if value.get("type") == "select":
        return str((value.get("select") or {}).get("name") or "")
    return ""


def _is_private_applyhome_page(page: dict[str, Any]) -> bool:
    properties = page.get("properties") or {}
    dedup_key = _property_text(properties, "dedup_key")
    if not dedup_key.startswith("apt_"):
        return False
    housing_program = _property_text(properties, "housing_program")
    source_category = _property_text(properties, "source_category")
    text = f"{housing_program} {source_category}"
    return "민영" in text or "誘쇱쁺" in text


class NotionClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, url, timeout=30, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"Notion API error {response.status_code}: {response.text}")
        return response.json()

    def database_property_names(self, database_id: str) -> set[str]:
        result = self._request("GET", f"https://api.notion.com/v1/databases/{database_id}")
        properties = result.get("properties") or {}
        return set(properties.keys())

    def find_page(self, database_id: str, dedup_key: str) -> str | None:
        payload = {
            "filter": {
                "property": "dedup_key",
                "rich_text": {"equals": dedup_key},
            },
            "page_size": 1,
        }
        result = self._request(
            "POST",
            f"https://api.notion.com/v1/databases/{database_id}/query",
            json=payload,
        )
        results = result.get("results") or []
        if not results:
            return None
        return str(results[0]["id"])

    def create_page(self, database_id: str, properties: dict[str, Any]) -> None:
        self._request(
            "POST",
            "https://api.notion.com/v1/pages",
            json={"parent": {"database_id": database_id}, "properties": properties},
        )

    def update_page(self, page_id: str, properties: dict[str, Any]) -> None:
        self._request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            json={"properties": properties},
        )

    def archive_page(self, page_id: str) -> None:
        self._request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            json={"archived": True},
        )

    def list_applyhome_pages(self, database_id: str) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor = None
        while True:
            payload: dict[str, Any] = {
                "filter": {
                    "property": "dedup_key",
                    "rich_text": {"starts_with": "apt_"},
                },
                "page_size": 100,
            }
            if cursor:
                payload["start_cursor"] = cursor
            result = self._request(
                "POST",
                f"https://api.notion.com/v1/databases/{database_id}/query",
                json=payload,
            )
            pages.extend(result.get("results") or [])
            if not result.get("has_more"):
                return pages
            cursor = result.get("next_cursor")


def _load_snapshot(path: Path) -> tuple[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    generated_at = _clean(payload.get("generated_at"))
    collected_date = _collected_date_from_generated_at(generated_at)
    items = payload.get("announcements") or []
    if not isinstance(items, list):
        raise ValueError("snapshot announcements must be a list")
    return collected_date, [item for item in items if isinstance(item, dict)]


def sync(snapshot_path: Path, database_id: str, token: str, limit: int | None) -> dict[str, Any]:
    collected_date, items = _load_snapshot(snapshot_path)
    client = NotionClient(token)
    allowed_properties = client.database_property_names(database_id)
    created = 0
    updated = 0
    skipped = 0
    archived = 0
    errors: list[str] = []
    for page in client.list_applyhome_pages(database_id):
        if not _is_private_applyhome_page(page):
            continue
        try:
            client.archive_page(str(page["id"]))
            archived += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"archive {page.get('id')}: {exc}")
    for item in items[:limit] if limit else items:
        dedup_key = _clean(item.get("source_id") or item.get("id"))
        if not dedup_key:
            skipped += 1
            continue
        try:
            properties = {
                key: value
                for key, value in _item_properties(item, collected_date).items()
                if key in allowed_properties
            }
            page_id = client.find_page(database_id, dedup_key)
            if page_id:
                client.update_page(page_id, properties)
                updated += 1
            else:
                client.create_page(database_id, properties)
                created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{dedup_key}: {exc}")
    return {
        "status": "ok" if not errors else "partial",
        "collected_date": collected_date,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "archived_private_applyhome": archived,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--database-id", default=_env("NOTION_DATABASE_ID", DEFAULT_DATABASE_ID))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    token = _env("NOTION_TOKEN")
    if not token:
        raise SystemExit("NOTION_TOKEN is required to sync announcements to Notion.")
    if not args.database_id:
        raise SystemExit("NOTION_DATABASE_ID is required.")
    if not args.input.exists():
        raise SystemExit(f"snapshot not found: {args.input}")

    result = sync(
        snapshot_path=args.input,
        database_id=args.database_id.replace("-", ""),
        token=token,
        limit=args.limit or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
