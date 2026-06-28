from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests


KST = timezone(timedelta(hours=9))
NOTION_VERSION = "2022-06-28"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "policy_rss_items.json"

POLICY_FEEDS = [
    {
        "department": "국무조정실",
        "rss": "https://www.korea.kr/rss/dept_opm.xml",
    },
    {
        "department": "국토교통부",
        "rss": "https://www.korea.kr/rss/dept_molit.xml",
    },
    {
        "department": "기획예산처",
        "rss": "https://www.korea.kr/rss/dept_mpb.xml",
    },
]

TOPIC_KEYWORDS = {
    "주거안정": ("주거안정", "주거 안정", "주거지원", "주거 지원", "주거비"),
    "청년주거": ("청년주택", "청년월세", "청년 주거", "청년 임대", "청년 전세"),
    "공공주택": ("공공주택", "공공임대", "행복주택", "매입임대", "전세임대"),
    "전월세": ("전세", "월세", "전월세", "임대차", "보증금", "전세사기"),
    "주택공급": ("주택공급", "주택 공급", "공급대책", "분양", "택지", "신도시"),
    "주거복지": ("주거복지", "주거급여", "취약계층", "쪽방", "고령자복지주택"),
    "부동산시장": ("부동산", "집값", "주택시장", "매매", "재건축", "재개발"),
}

TARGET_KEYWORDS = {
    "청년": ("청년", "대학생", "사회초년생"),
    "신혼부부": ("신혼", "신생아", "출산", "다자녀"),
    "무주택자": ("무주택",),
    "저소득층": ("저소득", "취약계층", "주거급여", "쪽방"),
    "고령자": ("고령자", "어르신", "노인"),
}

HOUSING_KEYWORDS = tuple(
    sorted(
        {
            keyword
            for keywords in TOPIC_KEYWORDS.values()
            for keyword in keywords
        }
        | {
            "주거",
            "주택",
            "임대",
            "청약",
            "전입가능",
            "입주자",
            "무주택",
        },
        key=len,
        reverse=True,
    )
)
EXCLUDE_TITLE_KEYWORDS = ("후보자", "인사청문", "임명", "방문", "회담")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _child_text(element: ET.Element, name: str) -> str:
    child = element.find(name)
    if child is not None and child.text:
        return _clean_text(child.text)
    for candidate in element:
        if candidate.tag.rsplit("}", 1)[-1] == name and candidate.text:
            return _clean_text(candidate.text)
    return ""


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST)
    except (TypeError, ValueError):
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            parsed = datetime.strptime(value[:19], pattern)
            return parsed.replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def _dedup_key(department: str, link: str, guid: str, title: str) -> str:
    raw = "|".join([department, link or guid or title])
    return "policy_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _classify(text: str) -> tuple[list[str], list[str], str]:
    topics = [
        topic
        for topic, keywords in TOPIC_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    targets = [
        target
        for target, keywords in TARGET_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    if not targets:
        targets = ["일반가구"]
    relevance = "높음" if len(topics) >= 2 or any(k in text for k in ("주거", "주택", "임대", "청약")) else "중간"
    return topics, targets, relevance


def _is_housing_related(text: str) -> bool:
    return any(keyword in text for keyword in HOUSING_KEYWORDS)


def _fetch_feed(feed: dict[str, str], timeout: int) -> list[dict[str, Any]]:
    response = requests.get(
        feed["rss"],
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 youth-housing-compass-policy-rss"},
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = root.findall(".//item")
    parsed: list[dict[str, Any]] = []
    for item in items:
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        guid = _child_text(item, "guid")
        description = _child_text(item, "description")
        published = _parse_date(_child_text(item, "pubDate") or _child_text(item, "dc:date"))
        text = " ".join(part for part in (title, description) if part)
        title_related = _is_housing_related(title)
        text_related = _is_housing_related(text)
        if not title or not text_related:
            continue
        if any(keyword in title for keyword in EXCLUDE_TITLE_KEYWORDS):
            continue
        if feed["department"] != "국토교통부" and not title_related:
            continue
        topics, targets, relevance = _classify(text)
        if not topics:
            topics = ["주거안정"]
        parsed.append(
            {
                "dedup_key": _dedup_key(feed["department"], link, guid, title),
                "title": title,
                "department": feed["department"],
                "published_at": published.isoformat() if published else "",
                "published_date": published.date().isoformat() if published else "",
                "collected_date": datetime.now(KST).date().isoformat(),
                "url": link,
                "rss": feed["rss"],
                "summary": description[:900],
                "topics": topics,
                "targets": targets,
                "relevance": relevance,
            }
        )
    return parsed


def collect(days_back: int, timeout: int) -> list[dict[str, Any]]:
    start_date = (datetime.now(KST).date() - timedelta(days=max(0, days_back)))
    items: dict[str, dict[str, Any]] = {}
    for feed in POLICY_FEEDS:
        for item in _fetch_feed(feed, timeout):
            published_date = item.get("published_date")
            if published_date and published_date < start_date.isoformat():
                continue
            items[item["dedup_key"]] = item
    return sorted(
        items.values(),
        key=lambda item: (item.get("published_at") or "", item.get("dedup_key") or ""),
        reverse=True,
    )


def _notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _notion_query_existing(database_id: str, token: str) -> set[str]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = _notion_headers(token)
    cursor = ""
    keys: set[str] = set()
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = requests.post(url, headers=headers, json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
        for page in data.get("results", []):
            prop = page.get("properties", {}).get("dedup_key", {})
            rich_text = prop.get("rich_text", []) if isinstance(prop, dict) else []
            value = "".join(part.get("plain_text", "") for part in rich_text)
            if value:
                keys.add(value)
        if not data.get("has_more"):
            return keys
        cursor = str(data.get("next_cursor") or "")


def _notion_create_page(database_id: str, token: str, item: dict[str, Any]) -> None:
    properties: dict[str, Any] = {
        "제목": {"title": [{"text": {"content": item["title"][:2000]}}]},
        "부처": {"select": {"name": item["department"]}},
        "수집일": {"date": {"start": item["collected_date"]}},
        "정책주제": {"multi_select": [{"name": value} for value in item["topics"]]},
        "대상": {"multi_select": [{"name": value} for value in item["targets"]]},
        "콘텐츠상태": {"status": {"name": "시작 전"}},
        "관련도": {"select": {"name": item["relevance"]}},
        "요약": {"rich_text": [{"text": {"content": item["summary"][:2000]}}]},
        "dedup_key": {"rich_text": [{"text": {"content": item["dedup_key"]}}]},
        "원문링크": {"url": item["url"] or None},
        "RSS": {"url": item["rss"]},
    }
    if item.get("published_date"):
        properties["발행일"] = {"date": {"start": item["published_date"]}}
    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_notion_headers(token),
        json={"parent": {"database_id": database_id}, "properties": properties},
        timeout=45,
    )
    response.raise_for_status()


def sync_notion(items: list[dict[str, Any]], database_id: str, token: str) -> int:
    existing = _notion_query_existing(database_id, token)
    created = 0
    for item in items:
        if item["dedup_key"] in existing:
            continue
        _notion_create_page(database_id, token, item)
        existing.add(item["dedup_key"])
        created += 1
        time.sleep(0.35)
    return created


def _write_output(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "feeds": POLICY_FEEDS,
                "count": len(items),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-notion", action="store_true")
    parser.add_argument("--database-id", default=_env("NOTION_POLICY_DATABASE_ID"))
    args = parser.parse_args()

    items = collect(args.days_back, max(5, args.timeout))
    _write_output(args.output, items)
    created = 0
    if not args.no_notion:
        token = _env("NOTION_TOKEN")
        if not token:
            raise SystemExit("NOTION_TOKEN is required.")
        if not args.database_id:
            raise SystemExit("NOTION_POLICY_DATABASE_ID is required.")
        created = sync_notion(items, args.database_id, token)
    print(
        json.dumps(
            {
                "status": "ok",
                "days_back": args.days_back,
                "collected": len(items),
                "created": created,
                "output": str(args.output),
                "departments": [feed["department"] for feed in POLICY_FEEDS],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
