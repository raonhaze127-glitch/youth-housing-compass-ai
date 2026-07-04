from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from bs4 import BeautifulSoup
import requests


KST = timezone(timedelta(hours=9))
NOTION_VERSION = "2022-06-28"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "seoul_redevelopment_progress.json"
DEFAULT_SITE_OUTPUT = PROJECT_ROOT / "data" / "seoul_redevelopment_sites.json"
SERVICE_NAME = "CleanupBussinessProgress"
SOURCE_NAME = "서울시 정비사업 추진경과"
CLEANUP_SITE_URL = "https://cleanup.seoul.go.kr/cleanup/bsnssttus/lscrMainIndx.do"

SEOUL_GU_BY_CODE = {
    "11110": "종로구",
    "11140": "중구",
    "11170": "용산구",
    "11200": "성동구",
    "11215": "광진구",
    "11230": "동대문구",
    "11260": "중랑구",
    "11290": "성북구",
    "11305": "강북구",
    "11320": "도봉구",
    "11350": "노원구",
    "11380": "은평구",
    "11410": "서대문구",
    "11440": "마포구",
    "11470": "양천구",
    "11500": "강서구",
    "11530": "구로구",
    "11545": "금천구",
    "11560": "영등포구",
    "11590": "동작구",
    "11620": "관악구",
    "11650": "서초구",
    "11680": "강남구",
    "11710": "송파구",
    "11740": "강동구",
}

STAGE_ALIASES = (
    ("정비구역지정", "정비구역지정"),
    ("추진위원", "추진위원회"),
    ("조합설립", "조합설립인가"),
    ("사업시행", "사업시행인가"),
    ("관리처분", "관리처분인가"),
    ("착공", "착공"),
    ("준공", "준공"),
)

PUBLIC_PROGRAM_PATTERNS = (
    ("공공재개발", re.compile(r"공공\s*재개발|공공재개발")),
    ("공공재건축", re.compile(r"공공\s*재건축|공공재건축")),
    ("신속통합기획", re.compile(r"신속\s*통합\s*기획|신속통합기획|신통기획")),
    ("모아타운", re.compile(r"모아\s*타운|모아타운|모아\s*주택|모아주택")),
)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _parse_day(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 8:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _stage_name(value: str) -> str:
    for needle, stage in STAGE_ALIASES:
        if needle in value:
            return stage
    return "기타"


def _public_program_classification(item: dict[str, Any]) -> tuple[bool, str, str]:
    text = " ".join(
        _clean(item.get(key))
        for key in (
            "project_name",
            "business_type",
            "site_stage",
            "stage",
            "district",
            "address_lot",
            "cafe_url",
            "site_url",
            "site_candidates",
            "latest_title",
            "detail",
        )
    )
    for label, pattern in PUBLIC_PROGRAM_PATTERNS:
        match = pattern.search(text)
        if match:
            return True, label, f"사업장/진행 정보에 '{match.group(0)}' 키워드 포함"
    if item.get("project_name") or item.get("business_type"):
        return False, "민간/일반", "공공사업 키워드 없음"
    return False, "미분류", "사업장명/사업유형 매칭 부족"


def _apply_public_program_classification(item: dict[str, Any]) -> None:
    is_public, program_type, reason = _public_program_classification(item)
    item["is_public_program"] = is_public
    item["public_program_type"] = program_type
    item["public_program_reason"] = reason


def _is_actual_approval(item: dict[str, Any]) -> bool:
    text = f"{item.get('detail_name', '')} {item.get('title', '')} {item.get('detail', '')}"
    return "인가" in text and "신청" not in text and "반려" not in text and "취소" not in text


def _normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    biz_no = _clean(row.get("BIZ_NO"))
    stage = _stage_name(_clean(row.get("SE_NM")))
    detail = _clean(row.get("DTL_PRCD_NM"))
    day = _parse_day(_clean(row.get("DAY")))
    district = SEOUL_GU_BY_CODE.get(biz_no.split("-", 1)[0], "")
    return {
        "biz_no": biz_no,
        "district": district,
        "stage": stage,
        "stage_raw": _clean(row.get("SE_NM")),
        "detail_code": _clean(row.get("DTL_PRCS_CD")),
        "detail_name": detail,
        "day": day,
        "title": _clean(row.get("TTL")),
        "detail": _clean(row.get("DTL_CN")),
    }


def _fetch_page(api_key: str, start: int, end: int, timeout: int) -> dict[str, Any]:
    url = f"http://openAPI.seoul.go.kr:8088/{api_key}/json/{SERVICE_NAME}/{start}/{end}/"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if SERVICE_NAME not in payload:
        result = payload.get("RESULT", {})
        raise RuntimeError(f"Seoul API error: {result.get('CODE')} {result.get('MESSAGE')}")
    return payload[SERVICE_NAME]


def _collect_events(api_key: str, max_events: int, timeout: int) -> list[dict[str, Any]]:
    page_size = 1000
    start = 1
    total = None
    events: list[dict[str, Any]] = []
    while total is None or start <= total:
        end = start + page_size - 1
        payload = _fetch_page(api_key, start, end, timeout)
        total = int(payload.get("list_total_count") or 0)
        rows = payload.get("row") or []
        if not rows:
            break
        events.extend(_normalize_event(row) for row in rows)
        if max_events and len(events) >= max_events:
            return events[:max_events]
        start += page_size
    return events


def _site_url(cafe_url: str) -> str:
    return f"https://cleanup.seoul.go.kr/cafe/mainIndx.do?cafeUrl={cafe_url}" if cafe_url else ""


def _collect_site_rows(timeout: int) -> list[dict[str, Any]]:
    response = requests.get(CLEANUP_SITE_URL, params={"cpage": 1, "pageSize": 2000}, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("table.board-list-tbl tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(cells) < 10:
            continue
        row_html = str(tr)
        cafe_match = re.search(r"cafeOpenPopup\('([^']+)'\)", row_html)
        map_match = re.search(r"mapOpenPopup\('([^']+)'\)", row_html)
        stage = _stage_name(cells[5])
        rows.append(
            {
                "district": cells[1],
                "business_type": cells[2],
                "project_name": cells[3],
                "address_lot": cells[4],
                "site_stage": cells[5],
                "stage": stage,
                "public_item_count": cells[6],
                "timeliness_rate": cells[7],
                "completeness_rate": cells[8],
                "cafe_url": cafe_match.group(1) if cafe_match else "",
                "site_url": _site_url(cafe_match.group(1) if cafe_match else ""),
                "map_id": map_match.group(1) if map_match else "",
            }
        )
        _apply_public_program_classification(rows[-1])
    return rows


def _pick_date(events: list[dict[str, Any]], stage: str, approval_only: bool = False) -> str:
    candidates = [item for item in events if item.get("stage") == stage and item.get("day")]
    if approval_only:
        approved = [item for item in candidates if _is_actual_approval(item)]
        if approved:
            candidates = approved
    return min((item["day"] for item in candidates), default="")


def _latest_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    dated = [item for item in events if item.get("day")]
    if not dated:
        return events[-1] if events else {}
    return max(dated, key=lambda item: item["day"])


def _schedule_summary(item: dict[str, Any]) -> str:
    parts = []
    for label, key in (
        ("사업시행인가", "project_approval_date"),
        ("관리처분인가", "management_disposal_date"),
        ("착공", "construction_start_date"),
        ("최근진행", "latest_progress_date"),
    ):
        value = item.get(key)
        if value:
            parts.append(f"{label}: {value}")
    if item.get("latest_stage"):
        parts.append(f"최근단계: {item['latest_stage']} / {item.get('latest_detail', '')}".strip())
    return "; ".join(parts)


def _site_candidate_text(site_rows: list[dict[str, Any]]) -> str:
    return " | ".join(
        f"{row['project_name']} ({row['address_lot']}, {row['site_stage']})"
        for row in site_rows[:10]
    )


def _enrich_with_site(item: dict[str, Any], site_rows: list[dict[str, Any]]) -> None:
    matches = [
        row
        for row in site_rows
        if row.get("district") == item.get("district") and row.get("stage") == item.get("stage")
    ]
    if len(matches) == 1:
        site = matches[0]
        item.update(
            {
                "project_name": site["project_name"],
                "address_lot": site["address_lot"],
                "business_type": site["business_type"],
                "site_url": site["site_url"],
                "map_id": site["map_id"],
                "site_match_status": "확정",
                "site_candidates": site["project_name"],
                "title": f"{site['project_name']} ({item['stage']})",
            }
        )
        _apply_public_program_classification(item)
        return
    item.update(
        {
            "project_name": "",
            "address_lot": "",
            "business_type": "",
            "site_url": "",
            "map_id": "",
            "site_match_status": "후보복수" if matches else "후보없음",
            "site_candidates": _site_candidate_text(matches),
        }
    )
    _apply_public_program_classification(item)


def _group_supply_candidates(
    events: list[dict[str, Any]], site_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_biz: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        biz_no = event.get("biz_no")
        if not biz_no:
            continue
        by_biz.setdefault(biz_no, []).append(event)

    candidates: list[dict[str, Any]] = []
    for biz_no, history in by_biz.items():
        project_approval_date = _pick_date(history, "사업시행인가", approval_only=True)
        management_disposal_date = _pick_date(history, "관리처분인가", approval_only=True)
        construction_start_date = _pick_date(history, "착공")
        completion_date = _pick_date(history, "준공")
        if completion_date:
            continue
        if not (project_approval_date or management_disposal_date or construction_start_date):
            continue

        latest = _latest_event(history)
        supply_stage = "착공" if construction_start_date else "관리처분인가" if management_disposal_date else "사업시행인가"
        district = latest.get("district") or SEOUL_GU_BY_CODE.get(biz_no.split("-", 1)[0], "")
        latest_title = latest.get("title") or latest.get("detail_name") or ""
        item = {
            "dedup_key": f"redevelop_{biz_no.replace('-', '_')}",
            "biz_no": biz_no,
            "district": district,
            "stage": supply_stage,
            "project_approval_date": project_approval_date,
            "management_disposal_date": management_disposal_date,
            "construction_start_date": construction_start_date,
            "completion_date": completion_date,
            "latest_progress_date": latest.get("day", ""),
            "latest_stage": latest.get("stage", ""),
            "latest_detail": latest.get("detail_name", ""),
            "latest_title": latest_title,
            "title": f"{district or '서울'} {biz_no} 공급예정지 ({supply_stage})",
            "detail": latest.get("detail", ""),
            "source": SOURCE_NAME,
            "supply_review": True,
            "content_status": "시작 전",
            "history_count": len(history),
            "history": sorted(
                [
                    {
                        "day": event.get("day", ""),
                        "stage": event.get("stage", ""),
                        "detail_name": event.get("detail_name", ""),
                        "title": event.get("title", ""),
                    }
                    for event in history
                ],
                key=lambda row: row.get("day", ""),
            ),
        }
        _enrich_with_site(item, site_rows)
        _apply_public_program_classification(item)
        item["schedule_summary"] = _schedule_summary(item)
        candidates.append(item)

    return sorted(
        candidates,
        key=lambda item: (
            item.get("management_disposal_date") or item.get("project_approval_date") or "",
            item.get("latest_progress_date") or "",
            item.get("biz_no") or "",
        ),
        reverse=True,
    )


def _site_row_key(row: dict[str, Any]) -> str:
    raw = row.get("cafe_url") or row.get("map_id") or row.get("project_name") or row.get("address_lot")
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "_", _clean(raw)).strip("_")
    return normalized or "unknown"


def _public_site_items(site_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in site_rows:
        if not row.get("is_public_program"):
            continue
        item = {
            "dedup_key": f"redevelop_site_{_site_row_key(row)}",
            "biz_no": "",
            "district": row.get("district", ""),
            "stage": row.get("stage") or "기타",
            "project_approval_date": "",
            "management_disposal_date": "",
            "construction_start_date": "",
            "completion_date": "",
            "latest_progress_date": "",
            "latest_stage": row.get("site_stage", ""),
            "latest_detail": row.get("site_stage", ""),
            "latest_title": row.get("project_name", ""),
            "title": f"{row.get('project_name') or row.get('district') or '서울'} (원본 공공사업장)",
            "detail": "서울시 정비사업 정보몽땅 사업장검색 원본 기준 공공사업 분류 항목입니다.",
            "source": SOURCE_NAME,
            "supply_review": False,
            "content_status": "시작 전",
            "history_count": 0,
            "history": [],
            "project_name": row.get("project_name", ""),
            "address_lot": row.get("address_lot", ""),
            "business_type": row.get("business_type", ""),
            "site_url": row.get("site_url", ""),
            "map_id": row.get("map_id", ""),
            "site_match_status": "확정",
            "site_candidates": row.get("project_name", ""),
            "is_public_program": True,
            "public_program_type": row.get("public_program_type", "미분류"),
            "public_program_reason": row.get("public_program_reason", ""),
        }
        item["schedule_summary"] = f"원본 진행단계: {row.get('site_stage', '')}".strip()
        items.append(item)
    return sorted(
        items,
        key=lambda item: (
            item.get("public_program_type", ""),
            item.get("district", ""),
            item.get("project_name", ""),
        ),
    )


def collect(api_key: str, max_events: int, max_items: int, timeout: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = _collect_events(api_key, max_events=max(0, max_events), timeout=max(5, timeout))
    site_rows = _collect_site_rows(timeout=max(5, timeout))
    items = _group_supply_candidates(events, site_rows)
    return (items[:max_items] if max_items else items), site_rows


def _notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _notion_existing(database_id: str, token: str) -> dict[str, str]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    cursor = ""
    pages: dict[str, str] = {}
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = requests.post(url, headers=_notion_headers(token), json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
        for page in data.get("results", []):
            prop = page.get("properties", {}).get("dedup_key", {})
            rich_text = prop.get("rich_text", []) if isinstance(prop, dict) else []
            value = "".join(part.get("plain_text", "") for part in rich_text)
            if value:
                pages[value] = page.get("id", "")
        if not data.get("has_more"):
            return pages
        cursor = str(data.get("next_cursor") or "")


def _date_prop(value: str) -> dict[str, Any] | None:
    return {"date": {"start": value}} if value else None


def _rich(value: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": value[:2000]}}]} if value else {"rich_text": []}


def _notion_properties(item: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "항목명": {"title": [{"text": {"content": item["title"][:2000]}}]},
        "사업번호": _rich(item["biz_no"]),
        "진행단계": {"select": {"name": item["stage"]}},
        "세부절차": _rich(item["latest_detail"]),
        "제목": _rich(item["latest_title"]),
        "상세내용": _rich(item["detail"]),
        "주요일정": _rich(item["schedule_summary"]),
        "콘텐츠상태": {"status": {"name": item["content_status"]}},
        "공급예정지검토": {"checkbox": bool(item.get("supply_review"))},
        "dedup_key": _rich(item["dedup_key"]),
        "source": {"select": {"name": SOURCE_NAME}},
        "사업장명": _rich(item.get("project_name", "")),
        "대표지번": _rich(item.get("address_lot", "")),
        "사업유형": _rich(item.get("business_type", "")),
        "지도ID": _rich(item.get("map_id", "")),
        "매칭상태": {"select": {"name": item.get("site_match_status", "후보없음")}},
        "사업장후보": _rich(item.get("site_candidates", "")),
        "공공사업여부": {"checkbox": bool(item.get("is_public_program"))},
        "공공사업구분": {"select": {"name": item.get("public_program_type", "미분류")}},
        "공공사업분류근거": _rich(item.get("public_program_reason", "")),
    }
    if item.get("site_url"):
        properties["사업장URL"] = {"url": item["site_url"]}
    if item.get("district"):
        properties["자치구"] = {"select": {"name": item["district"]}}
    for notion_name, key in (
        ("기준일", "latest_progress_date"),
        ("최근진행일", "latest_progress_date"),
        ("사업시행인가일", "project_approval_date"),
        ("관리처분인가일", "management_disposal_date"),
        ("착공일", "construction_start_date"),
    ):
        prop = _date_prop(item.get(key, ""))
        if prop:
            properties[notion_name] = prop
    return properties


def _notion_create_page(database_id: str, token: str, item: dict[str, Any]) -> None:
    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_notion_headers(token),
        json={"parent": {"database_id": database_id}, "properties": _notion_properties(item)},
        timeout=45,
    )
    response.raise_for_status()


def _notion_update_page(page_id: str, token: str, item: dict[str, Any]) -> None:
    response = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=_notion_headers(token),
        json={"properties": _notion_properties(item)},
        timeout=45,
    )
    response.raise_for_status()


def sync_notion(items: list[dict[str, Any]], database_id: str, token: str) -> tuple[int, int]:
    try:
        existing = _notion_existing(database_id, token)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "unknown"
        print(f"warning: skipped Notion sync: database access failed ({status})", file=sys.stderr)
        return 0, 0
    created = 0
    updated = 0
    for item in items:
        page_id = existing.get(item["dedup_key"])
        if page_id:
            _notion_update_page(page_id, token, item)
            updated += 1
        else:
            _notion_create_page(database_id, token, item)
            created += 1
        time.sleep(0.35)
    return created, updated


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_outputs(
    output: Path, site_output: Path, items: list[dict[str, Any]], site_rows: list[dict[str, Any]], max_events: int
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    _write_json(
        output,
        {
            "schema_version": 3,
            "generated_at": generated_at,
            "source": SOURCE_NAME,
            "criteria": "사업시행인가 이상 포함, 준공 완료 사업 제외",
            "site_match_note": "정비사업 추진경과 API의 BIZ_NO와 사업장검색 목록 사이에 공개 공통키가 없어 자치구+진행단계가 단일 후보일 때만 확정 매칭합니다.",
            "max_events": max_events,
            "count": len(items),
            "items": items,
        },
    )
    _write_json(
        site_output,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "source": "서울시 정비사업 정보몽땅 사업장검색",
            "count": len(site_rows),
            "items": site_rows,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-events", type=int, default=0)
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--site-output", type=Path, default=DEFAULT_SITE_OUTPUT)
    parser.add_argument("--api-key", default=_env("SEOUL_OPEN_API_KEY"))
    parser.add_argument("--database-id", default=_env("NOTION_REDEVELOPMENT_DATABASE_ID"))
    parser.add_argument("--sync-public-sites", action="store_true")
    parser.add_argument("--no-notion", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("SEOUL_OPEN_API_KEY is required.")
    items, site_rows = collect(args.api_key, max(0, args.max_events), max(0, args.max_items), max(5, args.timeout))
    _write_outputs(args.output, args.site_output, items, site_rows, max(0, args.max_events))
    created = 0
    updated = 0
    if not args.no_notion:
        token = _env("NOTION_TOKEN")
        if not token:
            raise SystemExit("NOTION_TOKEN is required.")
        if not args.database_id:
            raise SystemExit("NOTION_REDEVELOPMENT_DATABASE_ID is required.")
        notion_items = items + (_public_site_items(site_rows) if args.sync_public_sites else [])
        created, updated = sync_notion(notion_items, args.database_id, token)
    print(
        json.dumps(
            {
                "status": "ok",
                "collected": len(items),
                "site_rows": len(site_rows),
                "public_site_rows": len(_public_site_items(site_rows)),
                "created": created,
                "updated": updated,
                "output": str(args.output),
                "site_output": str(args.site_output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
