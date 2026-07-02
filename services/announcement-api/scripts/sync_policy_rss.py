from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode, urljoin
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import requests


KST = timezone(timedelta(hours=9))
NOTION_VERSION = "2022-06-28"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "policy_rss_items.json"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

POLICY_FEEDS = [
    {
        "department": "국무조정실",
        "rss": "https://www.korea.kr/rss/dept_opm.xml",
        "code": "A00004",
    },
    {
        "department": "국토교통부",
        "rss": "https://www.korea.kr/rss/dept_molit.xml",
        "code": "A00006",
    },
    {
        "department": "기획예산처",
        "rss": "https://www.korea.kr/rss/dept_mpb.xml",
        "code": "A00040",
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


def _extract_pdf_text(content: bytes) -> str:
    if not content.startswith(b"%PDF"):
        return ""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page in reader.pages[:12]:
        try:
            pages.append(page.extract_text() or "")
        except (KeyError, TypeError, ValueError):
            continue
    return _clean_text("\n".join(pages))


def _korea_attachment_urls(html_text: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    urls: list[str] = []
    for link in soup.find_all("a", href=True):
        label = link.get_text(" ", strip=True).lower()
        href = str(link.get("href") or "")
        lowered = href.lower()
        if ".pdf" in label or "download.do" in lowered:
            url = urljoin(base_url, href)
            if url not in urls:
                urls.append(url)
    return urls[:4]


def _curl_get(url: str, timeout: int, headers: dict[str, str] | None = None) -> requests.Response:
    command = [
        "curl",
        "-4",
        "-fsSL",
        "--connect-timeout",
        str(min(20, max(5, timeout // 2))),
        "--max-time",
        str(timeout),
    ]
    for key, value in (headers or {}).items():
        command.extend(["-H", f"{key}: {value}"])
    command.append(url)
    completed = subprocess.run(command, check=True, capture_output=True)
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response._content = completed.stdout
    response.encoding = response.apparent_encoding or "utf-8"
    return response


def _request_get(url: str, timeout: int, retries: int = 3, **kwargs: Any) -> requests.Response:
    last_error: Exception | None = None
    if "korea.kr" in url:
        try:
            return _curl_get(url, timeout, kwargs.get("headers"))
        except (subprocess.SubprocessError, OSError) as error:
            last_error = error
    for attempt in range(max(1, retries)):
        try:
            response = requests.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except (
            requests.ConnectTimeout,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.HTTPError,
        ) as error:
            last_error = error
            if attempt < max(1, retries) - 1:
                time.sleep(2 * (attempt + 1))
    try:
        return _curl_get(url, timeout, kwargs.get("headers"))
    except (subprocess.SubprocessError, OSError) as curl_error:
        if last_error:
            raise last_error
        raise requests.RequestException(f"failed to fetch {url}") from curl_error


def _fetch_article_text(url: str, timeout: int, retries: int) -> str:
    if not url:
        return ""
    response = _request_get(
        url,
        timeout=timeout,
        retries=retries,
        headers=DEFAULT_HEADERS,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    meta_parts = [
        tag.get("content", "")
        for tag in soup.find_all("meta")
        if str(tag.get("name") or tag.get("property") or "").lower()
        in {"description", "og:description", "twitter:description"}
    ]
    for tag in soup(["script", "style", "nav", "header", "footer", "form"]):
        tag.decompose()
    parts = [_clean_text(" ".join(meta_parts)), _clean_text(soup.get_text(" ", strip=True))]
    for attachment_url in _korea_attachment_urls(response.text, url):
        try:
            attachment = _request_get(
                attachment_url,
                timeout=timeout,
                retries=retries,
                headers=DEFAULT_HEADERS,
            )
            attachment.raise_for_status()
            text = _extract_pdf_text(attachment.content)
            if text:
                parts.append(text)
        except (requests.RequestException, OSError, KeyError, TypeError, ValueError):
            continue
    return _clean_text(" ".join(part for part in parts if part))




def _policy_item_from_parts(
    feed: dict[str, str],
    title: str,
    link: str,
    guid: str,
    description: str,
    published: datetime | None,
    timeout: int,
    retries: int,
) -> dict[str, Any] | None:
    text = " ".join(part for part in (title, description) if part)
    detail_text = ""
    title_related = _is_housing_related(title)
    text_related = _is_housing_related(text)
    if any(keyword in title for keyword in EXCLUDE_TITLE_KEYWORDS):
        return None
    if title and not text_related and link:
        detail_text = _fetch_article_text(link, timeout, retries)
        text = " ".join(part for part in (text, detail_text) if part)
        text_related = _is_housing_related(text)
    if not title or not text_related:
        return None
    if feed["department"] != "국토교통부" and not (title_related or _is_housing_related(detail_text)):
        return None
    topics, targets, relevance = _classify(text)
    if not topics:
        topics = ["주거안정"]
    summary = description or detail_text[:900]
    published_date = published.date().isoformat() if published else ""
    return {
        "dedup_key": _dedup_key(feed["department"], link, guid, title),
        "title": title,
        "department": feed["department"],
        "published_at": published.isoformat() if published else "",
        "published_date": published_date,
        "collected_date": datetime.now(KST).date().isoformat(),
        "url": link,
        "rss": feed["rss"],
        "summary": summary[:900],
        "topics": topics,
        "targets": targets,
        "relevance": relevance,
    }

def _fetch_feed(feed: dict[str, str], timeout: int, retries: int, start_date: str = "") -> list[dict[str, Any]]:
    response = _request_get(
        feed["rss"],
        timeout=timeout,
        retries=retries,
        headers=DEFAULT_HEADERS,
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
        published_date = published.date().isoformat() if published else ""
        if start_date and published_date and published_date < start_date:
            continue
        parsed_item = _policy_item_from_parts(
            feed, title, link, guid, description, published, timeout, retries
        )
        if parsed_item:
            parsed.append(parsed_item)
    return parsed




def _fetch_press_release_list(
    feed: dict[str, str], start_date: str, end_date: str, timeout: int, retries: int
) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "period": "day",
            "startDate": start_date,
            "endDate": end_date,
            "repCode": feed.get("code", ""),
        }
    )
    url = f"https://www.korea.kr/briefing/pressReleaseList.do?{query}"
    response = _request_get(url, timeout=timeout, retries=retries, headers=DEFAULT_HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="pressReleaseView.do?newsId="]'):
        href = str(link.get("href") or "")
        article_url = urljoin(url, href)
        if article_url in seen:
            continue
        seen.add(article_url)
        strong = link.find("strong")
        title = _clean_text(strong.get_text(" ", strip=True) if strong else link.get_text(" ", strip=True))
        text = _clean_text(link.get_text(" ", strip=True))
        published = None
        match = re.search(r"20\d{2}[.-]\d{2}[.-]\d{2}", text)
        if match:
            published = _parse_date(match.group(0).replace(".", "-"))
        parsed_item = _policy_item_from_parts(
            feed, title, article_url, article_url, "", published, timeout, retries
        )
        if parsed_item:
            parsed.append(parsed_item)
    return parsed

def collect(days_back: int, timeout: int, retries: int) -> tuple[list[dict[str, Any]], int]:
    start_date = (datetime.now(KST).date() - timedelta(days=max(0, days_back)))
    items: dict[str, dict[str, Any]] = {}
    successful_feeds = 0
    for feed in POLICY_FEEDS:
        try:
            feed_items = _fetch_feed(feed, timeout, retries, start_date.isoformat())
        except (requests.RequestException, ET.ParseError) as error:
            print(
                f"warning: skipped {feed['department']} RSS: {type(error).__name__}; trying list fallback",
                file=sys.stderr,
            )
            try:
                feed_items = _fetch_press_release_list(
                    feed, start_date.isoformat(), datetime.now(KST).date().isoformat(), timeout, retries
                )
            except requests.RequestException as fallback_error:
                print(
                    f"warning: skipped {feed['department']} list fallback: {type(fallback_error).__name__}",
                    file=sys.stderr,
                )
                continue
        successful_feeds += 1
        for item in feed_items:
            published_date = item.get("published_date")
            if published_date and published_date < start_date.isoformat():
                continue
            items[item["dedup_key"]] = item
    return (
        sorted(
            items.values(),
            key=lambda item: (item.get("published_at") or "", item.get("dedup_key") or ""),
            reverse=True,
        ),
        successful_feeds,
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
    try:
        existing = _notion_query_existing(database_id, token)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "unknown"
        print(
            f"warning: skipped Notion sync: database access failed ({status})",
            file=sys.stderr,
        )
        return 0
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
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-notion", action="store_true")
    parser.add_argument("--database-id", default=_env("NOTION_POLICY_DATABASE_ID"))
    args = parser.parse_args()

    items, successful_feeds = collect(args.days_back, max(5, args.timeout), max(1, args.retries))
    if successful_feeds == 0:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "all RSS feeds failed",
                    "days_back": args.days_back,
                    "collected": 0,
                    "created": 0,
                    "output": str(args.output),
                    "departments": [feed["department"] for feed in POLICY_FEEDS],
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)
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
                "successful_feeds": successful_feeds,
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
