from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable

import requests
from bs4 import BeautifulSoup

from ..models import Announcement
from ..sources import SourceError
from ..status import calculate_status, normalize_date
from .changes import ChangeTracker

APPLYHOME_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
LH_URL = "https://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1"
SH_BOARDS = {
    "공공분양": "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/list.do?multi_itm_seq=1",
    "공공임대": "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/list.do?multi_itm_seq=2",
}
SH_DETAIL = "https://www.i-sh.co.kr/app/lay2/program/S48T1581C563/www/brd/m_247/view.do?seq={seq}&multi_itm_seq={board}"
GH_URL = "https://www.gh.or.kr/gh/announcement-of-salerental001.do"

APPLYHOME_CHANNELS = (
    ("apt", "APT", "getAPTLttotPblancDetail"),
    ("officetell", "오피스텔/도시형", "getUrbtyOfctlLttotPblancDetail"),
    ("remndr", "APT 잔여세대", "getRemndrLttotPblancDetail"),
    ("public_rent", "공공지원민간임대", "getPblPvtRentLttotPblancDetail"),
    ("optional", "임의공급", "getOPTLttotPblancDetail"),
)
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
)


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
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    body = payload.get("response", {}).get("body", {}) if isinstance(payload, dict) else {}
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _fetch_applyhome(api_key: str, months_back: int, timeout: int, fetched_at: str) -> list[Announcement]:
    now = datetime.now()
    params_base = {
        "serviceKey": api_key, "pageNo": "1", "numOfRows": "100",
        "startmonth": (now - timedelta(days=30 * months_back)).strftime("%Y%m"),
        "endmonth": now.strftime("%Y%m"),
    }
    result: list[Announcement] = []
    for prefix, category, endpoint in APPLYHOME_CHANNELS:
        response = requests.get(f"{APPLYHOME_BASE}/{endpoint}", params=params_base, timeout=timeout)
        response.raise_for_status()
        for item in _json_items(response.json()):
            raw_id = str(item.get("PBLANC_NO") or item.get("HOUSE_MANAGE_NO") or "")
            if not raw_id:
                continue
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
                metadata={"address": address, "speculative_zone": item.get("SPECLT_RDN_EARTH_AT"), "constructor": item.get("CNSTRCT_ENTRPS_NM")},
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


def _fetch_lh(api_key: str, months_back: int, timeout: int, fetched_at: str) -> list[Announcement]:
    response = requests.get(LH_URL, params={"serviceKey": api_key, "pageNo": "1", "numOfRows": "100"}, timeout=timeout)
    response.raise_for_status()
    cutoff = datetime.now().date() - timedelta(days=31 * months_back)
    result = []
    for item in _json_items(response.json()):
        title = str(item.get("BBS_TL") or "")
        raw_id = str(item.get("BBS_SN") or "")
        if not raw_id or not any(word in title for word in ("분양", "청약", "공급", "행복주택", "공공주택", "입주자")):
            continue
        if any(word in title for word in ("입찰", "용역", "공사", "물품")):
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
            region=_infer_region(title), housing_type=str(item.get("AIS_TP_CD_NM") or "공공임대/분양"),
            url=str(item.get("LINK_URL") or "https://apply.lh.or.kr"), fetched_at=fetched_at,
            metadata={"notice_date": registered},
        ))
    return result


def _recent(raw: str, formats: tuple[str, ...], days: int = 100) -> str:
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw.strip(), fmt).date()
            return parsed.isoformat() if (datetime.now().date() - parsed).days <= days else ""
        except ValueError:
            continue
    return ""


def _fetch_sh(timeout: int, fetched_at: str) -> list[Announcement]:
    result = []
    for board, (housing_type, url) in enumerate(SH_BOARDS.items(), start=1):
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 youth-housing-compass"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            title = cells[1].get_text(" ", strip=True)
            link = cells[1].find("a")
            match = re.search(r"getDetailView\(['\"](\d+)", str(link.get("onclick", "")) if link else "")
            notice_date = _recent(cells[3].get_text(strip=True), ("%Y-%m-%d",))
            if not match or not notice_date or not any(word in title for word in INCLUDE_WORDS) or any(word in title for word in EXCLUDE_WORDS):
                continue
            district = next((name for name in SEOUL_DISTRICTS if name in title), "")
            source_id = f"sh_{match.group(1)}"
            result.append(_announcement(
                source_id=source_id, title=title, organization="SH", category="SH 공공주택",
                region="서울", district=district, housing_type=housing_type,
                url=SH_DETAIL.format(seq=match.group(1), board=board), fetched_at=fetched_at,
                metadata={"notice_date": notice_date},
            ))
    return result


def _fetch_gh(timeout: int, fetched_at: str) -> list[Announcement]:
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
            notice_date = _recent(cells[4].get_text(strip=True), ("%y.%m.%d", "%Y-%m-%d"))
            if not match or not notice_date or not any(word in title for word in INCLUDE_WORDS) or any(word in title for word in EXCLUDE_WORDS):
                continue
            city = next((name for name in GYEONGGI_CITIES if name in title), "")
            article = match.group(1)
            result.append(_announcement(
                source_id=f"gh_{article}", title=title, organization="GH", category="GH 공공주택",
                region="경기", district=f"{city}시" if city else "", housing_type="공공임대/분양",
                url=f"{GH_URL}?mode=view&articleNo={article}", fetched_at=fetched_at,
                metadata={"notice_date": notice_date},
            ))
    return result


class DirectAnnouncementSource:
    name = "direct"

    def __init__(self, api_key: str, timeout_seconds: int = 30, cache_ttl_seconds: int = 900):
        self.api_key = api_key
        self.timeout_seconds = min(timeout_seconds, 60)
        self.cache_ttl_seconds = max(60, cache_ttl_seconds)
        self.tracker = ChangeTracker()
        self._cache: list[Announcement] = []
        self._cache_at = 0.0
        self._errors: list[str] = []
        self._lock = Lock()

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def fetch(self, months_back: int = 2) -> list[Announcement]:
        now = time.time()
        with self._lock:
            if self._cache and now - self._cache_at < self.cache_ttl_seconds:
                return list(self._cache)
        fetched_at = datetime.now(timezone.utc).isoformat()
        jobs: dict[str, Callable[[], list[Announcement]]] = {
            "sh": lambda: _fetch_sh(self.timeout_seconds, fetched_at),
            "gh": lambda: _fetch_gh(self.timeout_seconds, fetched_at),
        }
        if self.api_key:
            jobs["applyhome"] = lambda: _fetch_applyhome(self.api_key, months_back, self.timeout_seconds, fetched_at)
            jobs["lh"] = lambda: _fetch_lh(self.api_key, months_back, self.timeout_seconds, fetched_at)
        else:
            self._errors = ["DATA_GO_KR_API_KEY가 없어 청약홈·LH 채널을 건너뜁니다."]
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
        unique = {item.source_id: item for item in collected if item.source_id and item.title}
        items = sorted(unique.values(), key=lambda item: (item.apply_end or item.metadata.get("notice_date") or ""), reverse=True)
        with self._lock:
            self._errors = errors
            if items:
                self._cache = items
                self._cache_at = now
            elif self._cache:
                return list(self._cache)
        if not items:
            raise SourceError("직접 수집 결과가 없습니다. " + " / ".join(errors[:3]))
        self.tracker.observe([item.to_dict() for item in items])
        return items

    def lookup(self, source_id: str) -> Announcement | None:
        for item in self.fetch():
            if source_id in {item.source_id, item.id}:
                return item
        return None
