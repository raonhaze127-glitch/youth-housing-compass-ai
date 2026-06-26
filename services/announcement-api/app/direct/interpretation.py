from __future__ import annotations

import io
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from ..models import Announcement
from ..status import calculate_status
from .http_compat import CurlRequestError, curl_bytes, curl_text


ALLOWED_NOTICE_HOSTS = (
    "apply.lh.or.kr",
    "lh.or.kr",
    "i-sh.co.kr",
    "gh.or.kr",
    "applyhome.co.kr",
)
INCLUDE_NOTICE_PATTERNS = (
    re.compile(r"입주자\s*모집"),
    re.compile(r"예비입주자\s*모집"),
    re.compile(r"모집\s*공고"),
    re.compile(r"공급\s*공고"),
    re.compile(r"본청약"),
)
EXCLUDE_NOTICE_PATTERNS = (
    re.compile(r"접수\s*(?:결과|현황)"),
    re.compile(r"접수\s*마감"),
    re.compile(r"신청\s*결과"),
    re.compile(r"신청\s*현황"),
    re.compile(r"마감\s*(?:현황|결과|단지|게시)"),
    re.compile(r"결과\s*(?:안내|게시|공지|알림)"),
    re.compile(r"청약\s*(?:신청\s*)?경쟁률|경쟁률\s*(?:게시|공지)"),
    re.compile(r"당첨자|발표|선정\s*결과|개찰\s*결과|추첨\s*결과"),
    re.compile(r"(?:예비)?입주자\s*선정\s*안내"),
    re.compile(r"서류\s*심사|자격\s*심사|입주\s*대상자"),
    re.compile(r"서류\s*(?:제출|접수)\s*안내"),
    re.compile(r"계약\s*(?:체결|결과)|결과\s*알림|동호표|마감\s*안내"),
    re.compile(r"배정\s*물량|공급\s*대상\s*주택\s*게시"),
    re.compile(r"(?:모집|청약|신청|공급)\s*관련\s*안내|사진\s*(?:정정|변경)\s*안내"),
    re.compile(r"공고문.*(?:수정|변경)|(?:수정|변경)\s*안내"),
    re.compile(r"정정\s*안내"),
    re.compile(r"민영\s*주택"),
)
NON_HOUSING_TYPES = ("용지", "상가", "산업시설", "업무시설", "유치원")

TARGET_KEYWORDS = (
    "청년",
    "대학생",
    "취업준비생",
    "신혼부부",
    "예비신혼부부",
    "한부모가족",
    "고령자",
    "주거급여수급자",
    "기초생활수급자",
    "장애인",
    "다자녀",
)
DOCUMENT_KEYWORDS = (
    "주민등록등본",
    "주민등록초본",
    "가족관계증명서",
    "혼인관계증명서",
    "소득금액증명원",
    "건강보험자격득실확인서",
    "건강보험료 납부확인서",
    "금융정보 제공동의서",
    "자산보유 사실확인서",
    "청약통장 순위확인서",
    "임대차계약서",
)

SECTION_PATTERNS = {
    "eligibility": re.compile(
        r"신청\s*자격|입주자\s*자격|자격\s*요건|공급\s*자격|무주택\s*세대"
    ),
    "schedule": re.compile(
        r"공급\s*일정|모집\s*일정|신청\s*일정|접수\s*기간|청약\s*접수"
    ),
    "target": re.compile(r"공급\s*대상|모집\s*대상|공급\s*호수"),
    "rent": re.compile(
        r"임대\s*조건|임대\s*보증금|월\s*임대료|공급\s*금액|분양\s*가격"
    ),
    "documents": re.compile(r"제출\s*서류|구비\s*서류|준비\s*서류"),
}

DATE_TOKEN = (
    r"(?:(?:20)?\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}|"
    r"20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일)"
)
SHORT_DATE_TOKEN = r"\d{1,2}[.\-/]\s*\d{1,2}"
DATE_RANGE_PATTERN = re.compile(
    rf"(?:접수\s*기간|온라인\s*접수\s*기간|신청\s*기간|청약\s*접수|청약\s*신청|인터넷\s*청약\s*신청|인터넷\s*접수|서류\s*접수|신청\s*접수)"
    rf"[\s\S]{{0,100}}?({DATE_TOKEN})(?:\s+\d{{1,2}}:\d{{2}})?[.\s]*(?:\([^)]{{1,5}}\))?[.\s]*(?:\d{{1,2}}:\d{{2}})?[.\s]*"
    rf"(?:~|∼|부터|－|–|—|-)[^\d]{{0,12}}({DATE_TOKEN}|{SHORT_DATE_TOKEN})"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def is_public_applyhome_notice(item: Announcement | dict[str, Any]) -> bool:
    if isinstance(item, Announcement):
        organization = item.organization
        metadata = item.metadata
        source_id = item.source_id
        category = item.category
        housing_type = item.housing_type
    else:
        organization = str(item.get("organization") or "")
        metadata = item.get("metadata") or {}
        source_id = str(item.get("source_id") or "")
        category = str(item.get("category") or item.get("source_category") or "")
        housing_type = str(item.get("housing_type") or item.get("house_type") or "")
    if organization != "청약홈" or not isinstance(metadata, dict):
        return False
    house_code = str(metadata.get("house_secd") or "").strip()
    house_name = str(metadata.get("house_secd_name") or "").strip()
    searchable = " ".join((house_name, category, housing_type))
    private_names = ("\ubbfc\uc601", "\uc0ac\uc124", "誘쇱쁺")
    public_names = ("\uad6d\ubbfc", "\uacf5\uacf5", "\uacf5\uacf5\uc9c0\uc6d0", "援??", "怨듦났")
    if house_code == "01" or any(name in searchable for name in private_names):
        return False
    if source_id.startswith("public_rent_"):
        return True
    return house_code in {"03", "04", "06"} or any(name in searchable for name in public_names)


def is_public_recruitment_notice(item: Announcement | dict[str, Any]) -> bool:
    if isinstance(item, Announcement):
        title = item.title
        housing_type = item.housing_type
        organization = item.organization
    else:
        title = str(item.get("title") or item.get("name") or "")
        housing_type = str(item.get("housing_type") or item.get("house_type") or "")
        organization = str(item.get("organization") or "")
    public_applyhome = is_public_applyhome_notice(item)
    if organization and organization not in {"LH", "SH", "GH"} and not public_applyhome:
        return False
    if any(word in housing_type or word in title for word in NON_HOUSING_TYPES):
        return False
    if not public_applyhome and not any(pattern.search(title) for pattern in INCLUDE_NOTICE_PATTERNS):
        return False
    return not any(pattern.search(title) for pattern in EXCLUDE_NOTICE_PATTERNS)


def _select_enrichment_candidates(
    candidates: list[Announcement], limit: int, offset: int = 0
) -> list[Announcement]:
    if limit <= 0:
        return []
    if offset > 0:
        return candidates[offset : offset + limit]

    organizations = ("LH", "SH", "GH", "청약홈")
    groups = {
        organization: sorted(
            [item for item in candidates if item.organization == organization],
            key=lambda item: (
                bool(item.apply_start and item.apply_end),
                bool(item.metadata.get("analysis_source")),
            ),
        )
        for organization in organizations
    }
    positions = {organization: 0 for organization in organizations}
    selected: list[Announcement] = []
    while len(selected) < limit:
        added = False
        for organization in organizations:
            position = positions[organization]
            group = groups[organization]
            if position >= len(group):
                continue
            selected.append(group[position])
            positions[organization] += 1
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
    return selected


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_soup(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
        tag.decompose()
    return _normalize_text(soup.get_text("\n", strip=True))


def _allowed_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_NOTICE_HOSTS)


def _attachment_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    candidates: list[str] = []
    signals = (
        ".pdf",
        ".hwp",
        ".hwpx",
        "filedown",
        "filedownload",
        "atchfile",
        "atchmnfl",
        "attach",
        "download",
        "mode=download",
    )
    for link in soup.find_all("a", href=True):
        href = str(link.get("href") or "")
        label = link.get_text(" ", strip=True)
        lowered = href.lower()
        if any(signal in lowered for signal in signals) or any(
            keyword in label for keyword in ("모집공고문", "공고문 보기", "첨부파일")
        ):
            candidate = urljoin(base_url, href)
            if _allowed_url(candidate) and candidate not in candidates:
                candidates.append(candidate)
    return candidates[:3]


def _sh_attachment_urls(html: str) -> list[str]:
    match = re.search(
        r"initParam\.downList\s*=\s*(\[[^;]+\])\s*;",
        html,
        re.DOTALL,
    )
    if not match:
        return []
    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    urls: list[str] = []
    for item in items:
        filename = str(item.get("oriFileNm") or "").lower()
        if not filename.endswith((".pdf", ".hwp", ".hwpx")):
            continue
        query = urlencode(
            {
                "brdId": item.get("brdId", ""),
                "seq": item.get("seq", ""),
                "fileTp": item.get("fileTp", "A"),
                "fileSeq": item.get("fileSeq", ""),
            }
        )
        urls.append(f"https://www.i-sh.co.kr/com/file/innoFD.do?{query}")
    return urls[:3]


def _extract_hwpx(content: bytes) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            lowered = name.lower()
            if not lowered.endswith(".xml") or not any(
                marker in lowered for marker in ("section", "content")
            ):
                continue
            root = ElementTree.fromstring(archive.read(name))
            chunks.extend(value.strip() for value in root.itertext() if value.strip())
    return _normalize_text(" ".join(chunks))


def _extract_attachment(url: str, timeout: int) -> tuple[str, str]:
    maximum = 25 * 1024 * 1024
    if "apply.gh.or.kr" in url:
        content = curl_bytes(url, timeout)
        declared = len(content)
    else:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            allow_redirects=True,
        )
        response.raise_for_status()
        declared = int(response.headers.get("Content-Length", "0") or 0)
        content = response.content
    if declared > maximum or len(content) > maximum:
        return "", "too_large"
    if content.startswith(b"%PDF"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages: list[str] = []
        for index in range(min(len(reader.pages), 20)):
            try:
                pages.append(reader.pages[index].extract_text() or "")
            except (KeyError, TypeError, ValueError):
                continue
        text = "\n".join(pages)
        return _normalize_text(text), "pdf"
    if content.startswith(b"PK\x03\x04"):
        return _extract_hwpx(content), "hwpx"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        return "", "hwp_unsupported"
    return "", "unknown"


def fetch_notice_text(
    announcement: Announcement, timeout: int = 40
) -> tuple[str, list[dict[str, Any]]]:
    if not _allowed_url(announcement.announcement_url):
        return "", []
    detail_url = str(announcement.metadata.get("detail_url") or "")
    if "apply.gh.or.kr" in detail_url and announcement.metadata.get("pbanc_no"):
        response_text = curl_text(
            detail_url,
            timeout,
            data={
                "previewYn": "0",
                "pbancNo": announcement.metadata.get("pbanc_no", ""),
                "pbancKndCd": announcement.metadata.get("pbanc_kind_code", ""),
                "bizTyNm": announcement.metadata.get("business_type_name", ""),
            },
        )
        response_base_url = detail_url
    elif "i-sh.co.kr" in announcement.announcement_url:
        parsed = urlparse(announcement.announcement_url)
        query = parse_qs(parsed.query)
        response = requests.post(
            announcement.announcement_url.split("?", 1)[0],
            data={
                "page": "1",
                "seq": (query.get("seq") or [""])[0],
                "multi_itm_seq": (query.get("multi_itm_seq") or [""])[0],
                "multi_itm_seqsStr": "",
            },
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Referer": announcement.announcement_url.replace("view.do", "list.do"),
            },
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        response_text = response.text
        response_base_url = announcement.announcement_url
    else:
        response = requests.get(
            announcement.announcement_url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        response_text = response.text
        response_base_url = announcement.announcement_url
    soup = BeautifulSoup(response_text, "html.parser")
    attachments: list[dict[str, Any]] = []
    parts = [_clean_soup(BeautifulSoup(response_text, "html.parser"))]
    attachment_urls = _attachment_urls(soup, response_base_url)
    if "i-sh.co.kr" in announcement.announcement_url:
        attachment_urls = list(
            dict.fromkeys(_sh_attachment_urls(response.text) + attachment_urls)
        )[:3]
    for url in attachment_urls:
        try:
            extracted, kind = _extract_attachment(url, timeout)
            attachments.append(
                {"url": url, "type": kind, "extracted": bool(extracted)}
            )
            if extracted:
                parts.append(extracted)
        except (
            requests.RequestException,
            CurlRequestError,
            OSError,
            KeyError,
            TypeError,
            ValueError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ):
            attachments.append({"url": url, "type": "failed", "extracted": False})
    return _normalize_text("\n".join(part for part in parts if part)), attachments


def _section_excerpt(text: str, pattern: re.Pattern[str], maximum: int = 900) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    excerpt = text[match.start() : match.start() + maximum]
    return _normalize_text(excerpt)


def _extract_sections(text: str, maximum: int = 1400) -> dict[str, str]:
    hits: list[tuple[int, str]] = []
    for name, pattern in SECTION_PATTERNS.items():
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        if name == "schedule":
            match = max(
                matches,
                key=lambda candidate: len(
                    re.findall(DATE_TOKEN, text[candidate.start() : candidate.start() + 2000])
                ),
            )
        elif name == "eligibility":
            match = max(
                matches,
                key=lambda candidate: (
                    sum(
                        marker in text[candidate.start() : candidate.start() + maximum]
                        for marker in ("무주택", "소득", "자산", "세대구성원", "%", "만 ")
                    )
                    + 2 * len(
                        re.findall(
                            r"\d{2,3}\s*%|만\s*\d{1,2}\s*세",
                            text[candidate.start() : candidate.start() + maximum],
                        )
                    )
                    - (2 if "자격요건 검증을 위한 정보" in text[candidate.start() : candidate.start() + maximum] else 0)
                ),
            )
        elif name == "rent":
            match = max(
                matches,
                key=lambda candidate: (
                    4 * len(
                        re.findall(
                            r"\d[\d,]*\s*(?:원|만원)",
                            text[candidate.start() : candidate.start() + maximum],
                        )
                    )
                    + sum(
                        marker in text[candidate.start() : candidate.start() + maximum]
                        for marker in ("보증금", "월 임대료", "만원", "원", "전환")
                    )
                ),
            )
        else:
            match = matches[0]
        hits.append((match.start(), name))
    hits.sort()
    sections: dict[str, str] = {}
    for index, (start, name) in enumerate(hits):
        end = hits[index + 1][0] if index + 1 < len(hits) else len(text)
        sections[name] = _normalize_text(text[start : min(end, start + maximum)])
    return sections


def _normalize_date_token(value: str, default_year: int | None = None) -> str:
    numbers = [int(number) for number in re.findall(r"\d+", value)]
    if len(numbers) == 2 and default_year:
        numbers.insert(0, default_year)
    if len(numbers) < 3:
        return ""
    year = numbers[0] + 2000 if numbers[0] < 100 else numbers[0]
    try:
        return date(year, numbers[1], numbers[2]).isoformat()
    except ValueError:
        return ""


def _application_period(text: str) -> tuple[str, str]:
    candidates: list[tuple[int, str, str]] = []
    for match in DATE_RANGE_PATTERN.finditer(text):
        start = _normalize_date_token(match.group(1))
        start_year = int(start[:4]) if start else None
        end = _normalize_date_token(match.group(2), start_year)
        if not start or not end or start > end:
            continue
        label = match.group(0)[: match.start(1) - match.start()]
        score = 0
        if re.search(r"온라인\s*접수|인터넷\s*접수|청약\s*접수", label):
            score += 8
        elif re.search(r"접수\s*기간|신청\s*기간|신청\s*접수", label):
            score += 5
        if "서류" in label:
            score -= 4
        if start != end:
            score += 2
        candidates.append((score, start, end))
    if not candidates:
        return "", ""
    _, start, end = max(candidates, key=lambda candidate: (candidate[0], candidate[2]))
    return start, end


def _age_range(text: str) -> tuple[int | None, int | None]:
    match = re.search(
        r"만\s*(\d{1,2})\s*세\s*(?:이상|초과)[^\n]{0,80}?"
        r"만\s*(\d{1,2})\s*세\s*(?:이하|미만)",
        text,
    )
    if not match:
        return None, None
    minimum = int(match.group(1)) + (1 if "초과" in match.group(0) else 0)
    maximum = int(match.group(2)) - (1 if "미만" in match.group(0) else 0)
    return minimum, maximum


def _condition_excerpt(text: str) -> str:
    patterns = (
        re.compile(r"(?:도시근로자|월평균\s*소득)[^\n]{0,220}?\d{2,3}\s*%"),
        re.compile(r"기준\s*중위소득[^\n]{0,220}?\d{2,3}\s*%"),
        re.compile(r"총자산[^\n]{0,180}?(?:원|만원)"),
        re.compile(r"자동차[^\n]{0,180}?(?:원|만원)"),
    )
    found: list[str] = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            found.append(_normalize_text(match.group(0)))
    return " · ".join(found)[:700]


def interpret_notice_text(text: str) -> dict[str, Any]:
    normalized = _normalize_text(text)
    sections = _extract_sections(normalized)
    eligibility_text = sections.get("eligibility", normalized)
    # 공급대상 표의 앞부분만 사용해 뒤이어 나오는 방문접수 예외 안내를
    # 실제 모집대상으로 오인하지 않도록 합니다.
    target_section = sections.get("target", eligibility_text)
    target_text = re.split(
        r"모집\s*지역|접수\s*기간|신청\s*방법|청약\s*접수",
        target_section,
        maxsplit=1,
    )[0][:500]
    document_text = sections.get("documents", normalized)
    start, end = _application_period(normalized)
    age_min, age_max = _age_range(eligibility_text)
    targets = tuple(keyword for keyword in TARGET_KEYWORDS if keyword in target_text)
    documents = tuple(keyword for keyword in DOCUMENT_KEYWORDS if keyword in document_text)
    income_condition = _condition_excerpt(eligibility_text)
    if not income_condition:
        income_condition = _condition_excerpt(normalized)
    homeless_required = bool(
        re.search(r"무주택\s*세대(?:구성원|주)|무주택자", eligibility_text)
    ) or None
    evidence_count = sum(
        bool(value)
        for value in (start and end, targets, documents, income_condition, sections.get("eligibility"))
    )
    quality = "high" if evidence_count >= 4 else "medium" if evidence_count >= 2 else "low"
    return {
        "apply_start": start,
        "apply_end": end,
        "target": targets,
        "age_min": age_min,
        "age_max": age_max,
        "homeless_required": homeless_required,
        "income_condition": income_condition,
        "required_documents": documents,
        "sections": sections,
        "analysis_quality": quality,
        "source_char_count": len(normalized),
    }


def enrich_announcement(announcement: Announcement, timeout: int = 40) -> Announcement:
    try:
        text, attachments = fetch_notice_text(announcement, timeout)
    except requests.RequestException as error:
        if announcement.metadata.get("analysis_source"):
            metadata = dict(announcement.metadata)
            metadata.pop("analysis_error", None)
            if metadata.get("analysis_quality") == "failed":
                metadata["analysis_quality"] = (
                    "medium"
                    if announcement.required_documents
                    or announcement.income_condition
                    or announcement.target
                    else "low"
                )
            return replace(announcement, metadata=metadata)
        metadata = {
            **announcement.metadata,
            "analysis_quality": "failed",
            "analysis_error": type(error).__name__,
        }
        return replace(announcement, metadata=metadata)
    if not text:
        return announcement
    interpreted = interpret_notice_text(text)
    start = interpreted["apply_start"] or announcement.apply_start
    end = interpreted["apply_end"] or announcement.apply_end
    targets = (
        interpreted["target"]
        if interpreted["target"] or "target" in interpreted["sections"]
        else announcement.target
    )
    title_targets = tuple(
        keyword for keyword in TARGET_KEYWORDS if keyword in announcement.title
    )
    targets = tuple(dict.fromkeys((*targets, *title_targets)))
    eligibility = interpreted["sections"].get("eligibility", "")
    rent = interpreted["sections"].get("rent", "")
    metadata = {
        **announcement.metadata,
        "analysis_quality": interpreted["analysis_quality"],
        "analysis_source": "official_notice_and_attachments",
        "source_char_count": interpreted["source_char_count"],
        "sections": interpreted["sections"],
        "attachments": attachments,
    }
    target_label = ", ".join(targets[:4]) if targets else "신청 대상 확인이 필요한"
    return replace(
        announcement,
        target=targets,
        apply_start=start,
        apply_end=end,
        status=calculate_status(start, end),
        schedule_confirmed=bool(start and end),
        age_min=interpreted["age_min"] if interpreted["age_min"] is not None else announcement.age_min,
        age_max=interpreted["age_max"] if interpreted["age_max"] is not None else announcement.age_max,
        homeless_required=(
            interpreted["homeless_required"]
            if interpreted["homeless_required"] is not None
            else announcement.homeless_required
        ),
        income_condition=interpreted["income_condition"] or announcement.income_condition,
        required_documents=interpreted["required_documents"] or announcement.required_documents,
        summary=(
            f"공식 공고문을 자동 분석한 {target_label} 대상 공공주택 공고입니다."
            if targets
            else f"공식 공고문을 자동 분석한 {target_label} 공공주택 공고입니다."
        ),
        eligibility_summary=eligibility[:700] or announcement.eligibility_summary,
        benefit_summary=rent[:700] or announcement.benefit_summary,
        metadata=metadata,
    )


def enrich_announcements(
    announcements: list[Announcement],
    limit: int = 12,
    timeout: int = 40,
    offset: int = 0,
) -> list[Announcement]:
    candidates = [item for item in announcements if is_public_recruitment_notice(item)]
    selected = _select_enrichment_candidates(candidates, limit, offset)
    if not selected:
        return announcements
    enriched: dict[str, Announcement] = {}
    originals = {item.source_id: item for item in selected}
    with ThreadPoolExecutor(max_workers=min(3, len(selected))) as executor:
        futures = {
            executor.submit(enrich_announcement, item, timeout): item.source_id
            for item in selected
        }
        for future in as_completed(futures):
            source_id = futures[future]
            try:
                enriched[source_id] = future.result()
            except Exception as error:
                original = originals[source_id]
                if original.metadata.get("analysis_source"):
                    enriched[source_id] = original
                else:
                    enriched[source_id] = replace(
                        original,
                        metadata={
                            **original.metadata,
                            "analysis_quality": "failed",
                            "analysis_error": type(error).__name__,
                        },
                    )
    return [enriched.get(item.source_id, item) for item in announcements]
