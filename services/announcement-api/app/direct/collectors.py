from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from ..models import Announcement
from ..repository import AnnouncementRepository
from ..sources import SourceError
from ..status import calculate_status, normalize_date
from .changes import ChangeTracker
from .http_compat import CurlRequestError, curl_text
from .interpretation import (
    interpret_notice_text,
    is_public_applyhome_notice,
    is_public_recruitment_notice,
)

KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


def _today_kst() -> date:
    return _now_kst().date()

APPLYHOME_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
LH_URL = "https://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1"
LH_WRTANC_BOARDS = (
    ("1026", "06", "공공임대"),
    ("1027", "05", "공공분양"),
)
SH_BOARDS = {
    "공공분양": "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/list.do?multi_itm_seq=1",
    "공공임대": "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/list.do?multi_itm_seq=2",
}
SH_DETAIL = "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/view.do?seq={seq}&multi_itm_seq={board}"
GH_URL = "https://www.gh.or.kr/gh/announcement-of-salerental001.do"
GH_APPLY_CHANNELS = {
    "rent": {
        "category": "GH 임대주택",
        "housing_type": "공공임대",
        "list_url": "https://apply.gh.or.kr/sb/sr/sr7150/selectPbancRentHouseList.do",
        "detail_url": "https://apply.gh.or.kr/sb/sr/sr7150/selectPbancDetailView.do",
    },
    "purchase": {
        "category": "GH 매입임대",
        "housing_type": "매입임대",
        "list_url": "https://apply.gh.or.kr/sb/sr/sr7155/selectPbancRentHouseList.do",
        "detail_url": "https://apply.gh.or.kr/sb/sr/sr7155/selectPbancDetailView.do",
    },
}

APPLYHOME_CHANNELS = (
    ("apt", "APT", "getAPTLttotPblancDetail"),
    ("officetell", "오피스텔/도시형", "getUrbtyOfctlLttotPblancDetail"),
    ("remndr", "APT 잔여세대", "getRemndrLttotPblancDetail"),
    ("public_rent", "공공지원민간임대", "getPblPvtRentLttotPblancDetail"),
    ("optional", "임의공급", "getOPTLttotPblancDetail"),
)
PUBLIC_HOUSING_ORGANIZATIONS = frozenset({"LH", "SH", "GH"})
AREA_CODES = {
    "100": "서울", "200": "인천", "300": "경기", "400": "부산", "401": "대구",
    "402": "광주", "403": "대전", "404": "울산", "405": "세종", "500": "강원",
    "600": "충북", "601": "충남", "700": "전북", "701": "전남", "712": "경북",
    "800": "경남", "900": "제주",
}
REGIONS = tuple(AREA_CODES.values())
SEOUL_DISTRICTS = (
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
)
GYEONGGI_CITIES = (
    "수원", "성남", "고양", "용인", "부천", "안산", "남양주", "안양", "화성", "평택",
    "의정부", "시흥", "파주", "김포", "광명", "광주", "군포", "오산", "이천", "양주",
    "구리", "안성", "포천", "의왕", "하남", "여주", "동두천", "과천", "가평", "양평",
    "연천",
)
HOUSING_TYPE_KEYWORDS = (
    "통합공공임대", "행복주택", "국민임대", "영구임대", "매입임대",
    "전세임대", "장기전세", "사회주택", "공공분양", "신혼희망타운",
)
GH_DISTRICT_ALIASES = {
    "다산": "남양주시",
    "평촌": "안양시",
    "탑석": "의정부시",
}


def _safe_collection_error(name: str, error: Exception) -> str:
    """Return an operator-facing error without URLs, query strings, or secrets."""
    if isinstance(error, requests.HTTPError) and error.response is not None:
        status = error.response.status_code
        reason = error.response.reason or "HTTP 오류"
        return f"{name} 수집 실패: HTTP {status} {reason}"
    if isinstance(error, requests.RequestException):
        return f"{name} 수집 실패: 요청 오류 ({type(error).__name__})"
    return f"{name} 수집 실패: 내부 오류 ({type(error).__name__})"


INCLUDE_WORDS = ("모집공고", "분양공고", "입주자 모집", "입주자모집", "공급공고", "청약공고", "본청약")
EXCLUDE_WORDS = ("당첨자", "발표", "계약대상", "선정결과", "취소", "명단")


def _digits(value: Any) -> int | None:
    text = "".join(character for character in str(value or "") if character.isdigit())
    return int(text) if text else None


def _view_count(value: Any) -> int | None:
    return _digits(value)


def _first_view_count(item: dict[str, Any]) -> int | None:
    for key in (
        "VIEW_CNT", "viewCnt", "view_count",
        "INQ_CNT", "inqCnt", "RDCNT", "rdcnt",
        "HIT", "hit", "HIT_CNT", "hitCnt",
    ):
        count = _view_count(item.get(key))
        if count is not None:
            return count
    return None


def _housing_type(title: str, fallback: str) -> str:
    return next((keyword for keyword in HOUSING_TYPE_KEYWORDS if keyword in title), fallback)


def _district(address: str) -> str:
    tokens = address.split()
    for token in tokens[1:]:
        if re.fullmatch(r"[가-힣]+[구군]", token):
            return token
    for token in tokens[1:]:
        if re.fullmatch(r"[가-힣]+시", token):
            return token
    return ""


def _announcement(
    *, source_id: str, title: str, organization: str, category: str, region: str,
    district: str = "", housing_type: str = "", start: str = "", end: str = "",
    url: str = "", units: int | None = None, fetched_at: str, metadata: dict[str, Any] | None = None,
) -> Announcement:
    start_date = normalize_date(start)
    end_date = normalize_date(end)
    status = calculate_status(start_date, end_date)
    return Announcement(
        id=f"direct:{source_id}", source_id=source_id, source_type="direct_collector",
        title=title.strip(), organization=organization, category=category, region=region or "전국",
        district=district, housing_type=housing_type or category, target=(), apply_start=start_date,
        apply_end=end_date, status=status, announcement_url=url,
        summary="기관 원본에서 직접 수집한 공고입니다. 세부 조건은 원문을 확인해주세요.",
        eligibility_summary="자격요건은 공고 원문과 사전 점검 결과를 함께 확인해야 합니다.",
        benefit_summary="", required_documents=(), total_units=units, fetched_at=fetched_at,
        schedule_confirmed=status != "unknown", metadata=metadata or {},
    )


def _json_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        direct_items = [item for item in payload if isinstance(item, dict)]
        if any(_is_announcement_record(item) for item in direct_items):
            return direct_items
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    body = payload.get("response", {}).get("body", {}) if isinstance(payload, dict) else {}
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    standard_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    if standard_items:
        return standard_items
    return _find_announcement_records(payload)


def _is_announcement_record(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("BBS_SN", "PBLANC_NO", "HOUSE_MANAGE_NO"))


def _find_announcement_records(payload: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if _is_announcement_record(payload):
            records.append(payload)
        else:
            for value in payload.values():
                records.extend(_find_announcement_records(value))
    elif isinstance(payload, list):
        for value in payload:
            records.extend(_find_announcement_records(value))
    return records


def _fetch_applyhome(
    api_key: str,
    days_back: int,
    timeout: int,
    fetched_at: str,
    include_private_housing: bool = False,
) -> list[Announcement]:
    now = _now_kst()
    params_base = {
        "serviceKey": api_key, "pageNo": "1", "numOfRows": "100",
        "startmonth": (now - timedelta(days=days_back)).strftime("%Y%m"),
        "endmonth": now.strftime("%Y%m"),
    }
    result: list[Announcement] = []
    seen_raw_ids: set[str] = set()
    public_prefixes = {"apt"}
    private_names = ("\ubbfc\uc601", "\uc0ac\uc124", "誘쇱쁺")
    public_names = ("\uad6d\ubbfc", "\uacf5\uacf5", "\uacf5\uacf5\uc9c0\uc6d0", "援??", "怨듦났")
    for prefix, category, endpoint in APPLYHOME_CHANNELS:
        if not include_private_housing and prefix not in public_prefixes:
            continue
        response = requests.get(f"{APPLYHOME_BASE}/{endpoint}", params=params_base, timeout=timeout)
        response.raise_for_status()
        for item in _json_items(response.json()):
            house_code = str(item.get("HOUSE_SECD") or "").strip()
            house_name = str(item.get("HOUSE_SECD_NM") or "").strip()
            house_detail = str(item.get("HOUSE_DTL_SECD_NM") or "").strip()
            searchable = " ".join((house_name, house_detail, category))
            if not include_private_housing:
                is_public = (
                    prefix == "public_rent"
                    or house_code in {"03", "04", "06"}
                    or any(name in searchable for name in public_names)
                )
                is_private = (house_code == "01" and not is_public) or any(name in searchable for name in private_names)
                if is_private or not is_public:
                    continue
            raw_id = str(item.get("PBLANC_NO") or item.get("HOUSE_MANAGE_NO") or "")
            if not raw_id or (not include_private_housing and raw_id in seen_raw_ids):
                continue
            if not include_private_housing:
                seen_raw_ids.add(raw_id)
            address = str(item.get("HSSPLY_ADRES") or "")
            area_code = str(item.get("SUBSCRPT_AREA_CODE") or "")
            result.append(_announcement(
                source_id=f"{prefix}_{raw_id}", title=str(item.get("HOUSE_NM") or ""),
                organization="청약홈", category=category,
                region=str(item.get("SUBSCRPT_AREA_CODE_NM") or AREA_CODES.get(area_code, "전국")),
                district=_district(address),
                housing_type=str(item.get("HOUSE_DTL_SECD_NM") or item.get("HOUSE_SECD_NM") or category),
                start=str(item.get("RCEPT_BGNDE") or ""), end=str(item.get("RCEPT_ENDDE") or ""),
                url=str(item.get("PBLANC_URL") or ""), units=_digits(item.get("TOT_SUPLY_HSHLDCO")),
                fetched_at=fetched_at,
                metadata={
                    "address": address,
                    "speculative_zone": item.get("SPECLT_RDN_EARTH_AT"),
                    "constructor": item.get("CNSTRCT_ENTRPS_NM"),
                    "view_count": _first_view_count(item),
                    "house_secd": house_code,
                    "house_secd_name": house_name,
                },
            ))
    return result


def _infer_region(title: str) -> str:
    for region in REGIONS:
        if region in title:
            return region
    for city in GYEONGGI_CITIES:
        if city in title:
            return "경기"
    return "전국"


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _lh_notice_url(item: dict[str, Any], housing_type: str = "") -> str:
    link_url = _first_text(item, "LINK_URL", "linkUrl", "link_url")
    pan_id = _first_text(item, "PAN_ID", "panId", "PANID", "OTXT_PAN_ID", "otxtPanId")
    if link_url and (not pan_id or "selectWrtancList.do" not in link_url):
        return link_url

    if pan_id:
        text = " ".join((housing_type, _first_text(item, "BBS_TL", "TITLE", "title")))
        is_sale = any(keyword in text for keyword in ("분양", "매각", "토지", "상가"))
        mi = _first_text(item, "MI", "mi") or ("1027" if is_sale else "1026")
        upp_ais_tp_cd = _first_text(item, "UPP_AIS_TP_CD", "uppAisTpCd") or ("05" if mi == "1027" else "06")
        params = {
            "ccrCnntSysDsCd": _first_text(item, "CCR_CNNT_SYS_DS_CD", "ccrCnntSysDsCd") or "02",
            "panId": pan_id,
            "aisTpCd": _first_text(item, "AIS_TP_CD", "aisTpCd"),
            "uppAisTpCd": upp_ais_tp_cd,
            "mi": mi,
            "panKdCd": _first_text(item, "PAN_KD_CD", "panKdCd"),
            "otxtPanId": _first_text(item, "OTXT_PAN_ID", "otxtPanId"),
        }
        return "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?" + urlencode(params)

    bbs_sn = _first_text(item, "BBS_SN", "bbsSn")
    if bbs_sn:
        return "https://apply.lh.or.kr/lhapply/apply/noti/an/view.do?" + urlencode({
            "mi": "1079",
            "ccrCnntSysDsCd": _first_text(item, "CCR_CNNT_SYS_DS_CD", "ccrCnntSysDsCd") or "02",
            "bbsSn": bbs_sn,
        })
    return "https://apply.lh.or.kr"


def _lh_region(value: str, title: str) -> str:
    if "서울" in value:
        return "서울"
    if "경기" in value:
        return "경기"
    if "인천" in value:
        return "인천"
    return _infer_region(title)


def _fetch_lh_wrtanc_boards(days_back: int, timeout: int, fetched_at: str) -> list[Announcement]:
    cutoff = _today_kst() - timedelta(days=days_back)
    result: list[Announcement] = []
    headers = {"User-Agent": "Mozilla/5.0 youth-housing-compass"}
    for mi, default_upp_ais_tp_cd, fallback_type in LH_WRTANC_BOARDS:
        response = requests.get(
            "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do",
            params={"mi": mi},
            timeout=timeout,
            headers=headers,
        )
        response.raise_for_status()
        response.encoding = getattr(response, "apparent_encoding", None) or getattr(response, "encoding", None)
        soup = BeautifulSoup(getattr(response, "text", ""), "html.parser")
        for row in soup.select(".bbs_ListA tbody tr"):
            cells = row.find_all("td")
            link = row.select_one(".wrtancInfoBtn")
            if len(cells) < 8 or not link:
                continue
            title_node = BeautifulSoup(str(link), "html.parser")
            for extra in title_node.select("em"):
                extra.decompose()
            title = title_node.get_text(" ", strip=True)
            pan_id = str(link.get("data-id1") or "").strip()
            if not title or not pan_id:
                continue
            registered = normalize_date(cells[5].get_text(" ", strip=True))
            if registered:
                try:
                    if date.fromisoformat(registered) < cutoff:
                        continue
                except ValueError:
                    pass
            housing_type = cells[1].get_text(" ", strip=True) or fallback_type
            if not is_public_recruitment_notice(
                {"title": title, "housing_type": housing_type, "organization": "LH"}
            ):
                continue
            item = {
                "PAN_ID": pan_id,
                "CCR_CNNT_SYS_DS_CD": str(link.get("data-id2") or "").strip(),
                "UPP_AIS_TP_CD": str(link.get("data-id3") or default_upp_ais_tp_cd).strip(),
                "AIS_TP_CD": str(link.get("data-id4") or "").strip(),
                "MI": mi,
                "BBS_TL": title,
            }
            result.append(_announcement(
                source_id=f"lh_{pan_id}",
                title=title,
                organization="LH",
                category="LH 공공주택",
                region=_lh_region(cells[3].get_text(" ", strip=True), title),
                housing_type=housing_type,
                end=cells[6].get_text(" ", strip=True),
                url=_lh_notice_url(item, housing_type),
                fetched_at=fetched_at,
                metadata={"notice_date": registered, "view_count": _view_count(cells[8].get_text(" ", strip=True))},
            ))
    return list({item.source_id: item for item in result}.values())


def _fetch_lh(api_key: str, days_back: int, timeout: int, fetched_at: str) -> list[Announcement]:
    today = _today_kst()
    cutoff = today - timedelta(days=days_back)
    result = []
    page_size = 100
    for page in range(1, 11):
        response = requests.get(
            LH_URL,
            params={
                "ServiceKey": api_key,
                "PG_SZ": str(page_size),
                "SCH_ST_DT": cutoff.isoformat(),
                "SCH_ED_DT": today.isoformat(),
                "PAGE": str(page),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        items = _json_items(response.json())
        if not items:
            break
        for item in items:
            title = str(item.get("BBS_TL") or "")
            raw_id = _first_text(item, "BBS_SN", "bbsSn", "PAN_ID", "panId", "PANID")
            housing_type = str(item.get("AIS_TP_CD_NM") or "공공임대/분양")
            if not raw_id or not is_public_recruitment_notice(
                {"title": title, "housing_type": housing_type, "organization": "LH"}
            ):
                continue
            registered = normalize_date(str(item.get("BBS_WOU_DTTM") or "")[:10])
            if registered:
                try:
                    if date.fromisoformat(registered) < cutoff:
                        continue
                except ValueError:
                    pass
            result.append(_announcement(
                source_id=f"lh_{raw_id}", title=title, organization="LH", category="LH 공공주택",
                region=_infer_region(title), housing_type=housing_type,
                url=_lh_notice_url(item, housing_type), fetched_at=fetched_at,
                metadata={"notice_date": registered, "view_count": _first_view_count(item)},
            ))
        if len(items) < page_size:
            break
    by_source_id = {item.source_id: item for item in result}
    for item in _fetch_lh_wrtanc_boards(days_back, timeout, fetched_at):
        by_source_id[item.source_id] = item
    return list(by_source_id.values())


def _recent(raw: str, formats: tuple[str, ...], days: int = 100) -> str:
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw.strip(), fmt).date()
            return parsed.isoformat() if (_today_kst() - parsed).days <= days else ""
        except ValueError:
            continue
    return ""


def _fetch_sh(timeout: int, fetched_at: str, days_back: int = 100) -> list[Announcement]:
    result = []
    for board, (housing_type, url) in enumerate(SH_BOARDS.items(), start=1):
        for page in range(1, 11):
            response = requests.get(
                url,
                params={"page": page},
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 youth-housing-compass"},
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            saw_recent_row = False
            for row in soup.select("table tr"):
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue
                title = cells[1].get_text(" ", strip=True)
                link = cells[1].find("a")
                match = re.search(r"getDetailView\(['\"](\d+)", str(link.get("onclick", "")) if link else "")
                notice_date = _recent(cells[3].get_text(strip=True), ("%Y-%m-%d",), days_back)
                if notice_date:
                    saw_recent_row = True
                if not match or not notice_date or not is_public_recruitment_notice(
                    {"title": title, "housing_type": housing_type, "organization": "SH"}
                ):
                    continue
                district = next((name for name in SEOUL_DISTRICTS if name in title), "")
                source_id = f"sh_{match.group(1)}"
                result.append(_announcement(
                    source_id=source_id, title=title, organization="SH", category="SH 공공주택",
                    region="서울", district=district, housing_type=_housing_type(title, housing_type),
                    url=SH_DETAIL.format(seq=match.group(1), board=board), fetched_at=fetched_at,
                    metadata={"notice_date": notice_date, "view_count": _view_count(cells[4].get_text(" ", strip=True))},
                ))
            if not saw_recent_row:
                break
    unique_by_title: dict[str, Announcement] = {}
    for item in result:
        normalized_title = re.sub(r"^(?:NEW\s*)?(?:\[수정\]\s*)?", "", item.title).strip()
        unique_by_title.setdefault(normalized_title, item)
    return list(unique_by_title.values())


def _gh_district(title: str) -> str:
    alias = next((district for keyword, district in GH_DISTRICT_ALIASES.items() if keyword in title), "")
    if alias:
        return alias
    city = next((name for name in GYEONGGI_CITIES if name in title), "")
    if not city:
        return ""
    return f"{city}{'군' if city in {'가평', '양평', '연천'} else '시'}"


def _gh_detail_district(text: str) -> str:
    matches = re.findall(
        r"(?:소재지|공급\s*위치)\s*:?[\s\n]*(?:경기도\s*)?([가-힣]+(?:시|군))",
        text,
    )
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else ""


def _parse_gh_apply_list(
    html: str,
    channel: str,
    fetched_at: str,
    days_back: int,
) -> list[Announcement]:
    config = GH_APPLY_CHANNELS[channel]
    cutoff = _today_kst() - timedelta(days=days_back)
    result: list[Announcement] = []
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("table tbody tr"):
        link = row.select_one("a[data-pbancno]")
        cells = row.find_all("td")
        if not link or len(cells) < 8:
            continue
        pbanc_no = str(link.get("data-pbancno") or "").strip()
        title = link.get_text(" ", strip=True)
        pbanc_kind = str(link.get("data-pbanckndcd") or "").strip()
        business_type = str(link.get("data-biztynm") or "").strip()
        notice_date = normalize_date(cells[5].get_text(" ", strip=True))
        apply_end = normalize_date(cells[6].get_text(" ", strip=True))
        listed_status = cells[7].get_text(" ", strip=True)
        view_count = _view_count(cells[9].get_text(" ", strip=True)) if len(cells) > 9 else None
        is_active = listed_status in {"공고중", "접수중"}
        if notice_date:
            try:
                if date.fromisoformat(notice_date) < cutoff and not is_active:
                    continue
            except ValueError:
                pass
        housing_type = _housing_type(title, business_type or str(config["housing_type"]))
        if not pbanc_no or not is_public_recruitment_notice(
            {"title": title, "housing_type": housing_type, "organization": "GH"}
        ):
            continue
        search_url = f"{config['list_url']}?{urlencode({'searchTitle': title})}"
        result.append(
            _announcement(
                source_id=f"gh_apply_{channel}_{pbanc_no}",
                title=title,
                organization="GH",
                category=str(config["category"]),
                region="경기" if "경기" in cells[3].get_text(" ", strip=True) else _infer_region(title),
                district=_gh_district(title),
                housing_type=housing_type,
                end=apply_end,
                url=search_url,
                fetched_at=fetched_at,
                metadata={
                    "notice_date": notice_date,
                    "listed_status": listed_status,
                    "gh_apply_channel": channel,
                    "pbanc_no": pbanc_no,
                    "pbanc_kind_code": pbanc_kind,
                    "business_type_name": business_type,
                    "detail_url": config["detail_url"],
                    "view_count": view_count,
                },
            )
        )
    return result


def _fetch_gh_apply_channel(
    channel: str, timeout: int, fetched_at: str, days_back: int
) -> list[Announcement]:
    config = GH_APPLY_CHANNELS[channel]
    result: list[Announcement] = []
    for page in range(1, 11):
        html = curl_text(
            str(config["list_url"]),
            timeout,
            data={
                "pageIndex": page,
                "searchArea": "",
                "searchCate": "",
                "searchState": "",
                "searchTitle": "",
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        if not soup.select_one("a[data-pbancno]"):
            break
        page_items = _parse_gh_apply_list(html, channel, fetched_at, days_back)
        for item in page_items:
            metadata = item.metadata
            try:
                detail_html = curl_text(
                    str(metadata["detail_url"]),
                    timeout,
                    data={
                        "previewYn": "0",
                        "pbancNo": metadata["pbanc_no"],
                        "pbancKndCd": metadata["pbanc_kind_code"],
                        "bizTyNm": metadata["business_type_name"],
                    },
                )
                detail_text = BeautifulSoup(detail_html, "html.parser").get_text("\n", strip=True)
                interpreted = interpret_notice_text(detail_text)
                start = interpreted["apply_start"] or item.apply_start
                end = interpreted["apply_end"] or item.apply_end
                item = replace(
                    item,
                    district=item.district or _gh_detail_district(detail_text),
                    apply_start=start,
                    apply_end=end,
                    status=calculate_status(start, end),
                    schedule_confirmed=bool(start and end),
                )
            except (CurlRequestError, KeyError, TypeError, ValueError):
                pass
            result.append(item)
        if len(soup.select("a[data-pbancno]")) < 10:
            break
    return result


def _fetch_gh_legacy(timeout: int, fetched_at: str, days_back: int = 100) -> list[Announcement]:
    result = []
    for page in range(1, 4):
        response = requests.get(GH_URL, params={"pageIndex": page, "article.offset": (page - 1) * 10, "articleLimit": 10}, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 youth-housing-compass"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) < 6 or cells[1].get_text(strip=True) != "주택":
                continue
            title = cells[2].get_text(" ", strip=True)
            link = cells[2].find("a", href=True)
            match = re.search(r"articleNo=(\d+)", str(link.get("href", "")) if link else "")
            notice_date = _recent(
                cells[4].get_text(strip=True), ("%y.%m.%d", "%Y-%m-%d"), days_back
            )
            if not match or not notice_date or not is_public_recruitment_notice(
                {"title": title, "housing_type": "공공임대/분양", "organization": "GH"}
            ):
                continue
            city = next((name for name in GYEONGGI_CITIES if name in title), "")
            article = match.group(1)
            result.append(_announcement(
                source_id=f"gh_{article}", title=title, organization="GH", category="GH 공공주택",
                region="경기", district=f"{city}시" if city else "", housing_type=_housing_type(title, "공공임대/분양"),
                url=f"{GH_URL}?mode=view&articleNo={article}", fetched_at=fetched_at,
                metadata={"notice_date": notice_date, "view_count": _view_count(cells[5].get_text(" ", strip=True))},
            ))
    return result


def _fetch_gh(timeout: int, fetched_at: str, days_back: int = 100) -> list[Announcement]:
    result: list[Announcement] = []
    successful_channels = 0
    for channel in GH_APPLY_CHANNELS:
        try:
            result.extend(_fetch_gh_apply_channel(channel, timeout, fetched_at, days_back))
            successful_channels += 1
        except (CurlRequestError, requests.RequestException, KeyError, TypeError, ValueError):
            continue
    if successful_channels:
        return list({item.source_id: item for item in result}.values())
    return _fetch_gh_legacy(timeout, fetched_at, days_back)


class DirectAnnouncementSource:
    name = "direct"

    def __init__(
        self,
        api_key: str,
        timeout_seconds: int = 30,
        cache_ttl_seconds: int = 900,
        database_path: Path | None = None,
        sync_interval_seconds: int = 86400,
        include_private_housing: bool = False,
    ):
        self.api_key = api_key
        self.timeout_seconds = min(timeout_seconds, 60)
        self.cache_ttl_seconds = max(60, cache_ttl_seconds)
        self.sync_interval_seconds = max(3600, sync_interval_seconds)
        self.include_private_housing = include_private_housing
        self.repository = AnnouncementRepository(database_path) if database_path else None
        self.tracker = ChangeTracker()
        self._cache: list[Announcement] = []
        self._cache_at = 0.0
        self._errors: list[str] = []
        self._lock = Lock()

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def sync_status(self) -> dict[str, Any]:
        state = self.repository.sync_state(self.name) if self.repository else None
        return {
            "stored_count": len(self._stored_items()),
            "last_success_at": state.get("last_success_at") if state else None,
            "window_start": state.get("window_start") if state else None,
            "window_end": state.get("window_end") if state else None,
            "last_item_count": state.get("item_count") if state else None,
        }

    def _stored_items(self) -> list[Announcement]:
        if not self.repository:
            return self._visible_items(self._cache)
        items = []
        for payload in self.repository.list_payloads():
            status = calculate_status(
                str(payload.get("apply_start") or ""), str(payload.get("apply_end") or "")
            )
            payload["status"] = status
            announcement = Announcement(**payload)
            if self._is_visible(announcement):
                items.append(announcement)
        return sorted(
            items,
            key=lambda item: item.apply_end or item.metadata.get("notice_date") or "",
            reverse=True,
        )

    def _is_visible(self, item: Announcement) -> bool:
        return (
            self.include_private_housing
            or item.organization in PUBLIC_HOUSING_ORGANIZATIONS
            or is_public_applyhome_notice(item)
        )

    def _visible_items(self, items: list[Announcement]) -> list[Announcement]:
        return [item for item in items if self._is_visible(item)]

    def _sync_is_due(self) -> bool:
        if not self.repository:
            return True
        state = self.repository.sync_state(self.name)
        if not state:
            return True
        try:
            last_success = datetime.fromisoformat(str(state["last_success_at"]))
        except (TypeError, ValueError):
            return True
        return (datetime.now(timezone.utc) - last_success).total_seconds() >= self.sync_interval_seconds

    def fetch(
        self,
        months_back: int = 2,
        days_back: int | None = None,
        force_refresh: bool = False,
    ) -> list[Announcement]:
        now = time.time()
        with self._lock:
            if self._cache and not force_refresh and now - self._cache_at < self.cache_ttl_seconds:
                return self._visible_items(self._cache)
        stored = self._stored_items()
        if stored and not force_refresh and not self._sync_is_due():
            with self._lock:
                self._cache = stored
                self._cache_at = now
            return stored

        bootstrap = not stored
        lookback_days = days_back or (max(90, months_back * 31) if bootstrap else 7)
        fetched_at = datetime.now(timezone.utc).isoformat()
        jobs: dict[str, Callable[[], list[Announcement]]] = {
            "sh": lambda: _fetch_sh(self.timeout_seconds, fetched_at, lookback_days),
            "gh": lambda: _fetch_gh(self.timeout_seconds, fetched_at, lookback_days),
        }
        if self.api_key:
            jobs["applyhome"] = lambda: _fetch_applyhome(
                self.api_key,
                lookback_days,
                self.timeout_seconds,
                fetched_at,
                self.include_private_housing,
            )
            jobs["lh"] = lambda: _fetch_lh(
                self.api_key, lookback_days, self.timeout_seconds, fetched_at
            )
            self._errors = []
        else:
            self._errors = ["DATA_GO_KR_API_KEY가 없어 LH 채널을 건너뜁니다."]
        collected: list[Announcement] = []
        errors = list(self._errors)
        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            futures = {executor.submit(callback): name for name, callback in jobs.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    collected.extend(future.result())
                except Exception as error:
                    errors.append(_safe_collection_error(name, error))
        unique = {
            item.source_id: item
            for item in collected
            if item.source_id and item.title and is_public_recruitment_notice(item)
        }
        items = sorted(unique.values(), key=lambda item: (item.apply_end or item.metadata.get("notice_date") or ""), reverse=True)
        if self.repository and items:
            self.repository.upsert([item.to_dict() for item in items], fetched_at)
            window_end = _today_kst()
            self.repository.record_sync(
                self.name,
                (window_end - timedelta(days=lookback_days)).isoformat(),
                window_end.isoformat(),
                len(items),
                fetched_at,
            )
            items = self._stored_items()
        with self._lock:
            self._errors = errors
            if items:
                self._cache = items
                self._cache_at = now
            elif self._cache:
                return list(self._cache)
        if not items and stored:
            with self._lock:
                self._cache = stored
                self._cache_at = now
            return stored
        if not items:
            raise SourceError("직접 수집 결과가 없습니다. " + " / ".join(errors[:3]))
        self.tracker.observe([item.to_dict() for item in items])
        return items

    def lookup(self, source_id: str) -> Announcement | None:
        for item in self.fetch():
            if source_id in {item.source_id, item.id}:
                return item
        return None
