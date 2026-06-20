from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..sources import SourceError
from ..upstream import BinaryResponse
from .collectors import DirectAnnouncementSource
from .scoring import competition_estimate, match_payload, score_payload


def _escape_ics(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _section_windows(text: str) -> dict[str, str]:
    groups = {
        "자격": ("신청자격", "자격요건", "입주자격", "공급자격"),
        "공급일정": ("공급일정", "신청일정", "청약일정", "접수기간"),
        "공급대상": ("공급대상", "모집대상", "공급호수"),
        "공급금액": ("공급금액", "임대조건", "보증금", "분양가격"),
        "준비서류": ("제출서류", "구비서류", "준비서류"),
        "유의사항": ("유의사항", "주의사항", "기타사항"),
    }
    result = {}
    lowered = text.lower()
    for label, keywords in groups.items():
        positions = [lowered.find(keyword.lower()) for keyword in keywords]
        positions = [position for position in positions if position >= 0]
        if positions:
            start = min(positions)
            result[label] = text[start : start + 1800].strip()
    return result


def _attachment_text(url: str, timeout: int) -> tuple[str, str]:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 youth-housing-compass"})
    response.raise_for_status()
    if len(response.content) > 15 * 1024 * 1024:
        return "", "too_large"
    lowered = url.lower().split("?", 1)[0]
    if lowered.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(response.content))
        return " ".join((page.extract_text() or "") for page in reader.pages), "pdf"
    if lowered.endswith(".hwpx"):
        chunks: list[str] = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".xml") and ("section" in name.lower() or "content" in name.lower()):
                    root = ElementTree.fromstring(archive.read(name))
                    chunks.extend(text for text in root.itertext() if text.strip())
        return " ".join(chunks), "hwpx"
    return "", "unsupported"


class DirectFeatureClient:
    def __init__(self, source: DirectAnnouncementSource, timeout_seconds: int = 30):
        self.source = source
        self.timeout_seconds = min(timeout_seconds, 60)

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        return score_payload(payload)

    def match(self, payload: dict[str, Any]) -> dict[str, Any]:
        return match_payload(payload)

    def notice_raw(self, notice_id: str, force_refresh: bool = False) -> dict[str, Any]:
        del force_refresh
        announcement = self.source.lookup(notice_id)
        if announcement is None:
            raise SourceError("직접 수집 캐시에서 공고를 찾지 못했습니다.")
        if not announcement.announcement_url:
            raise SourceError("공고 원문 URL이 없습니다.")
        try:
            response = requests.get(
                announcement.announcement_url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0 youth-housing-compass"},
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise SourceError(f"공고 원문 조회에 실패했습니다: {error}") from error
        response.encoding = response.apparent_encoding or response.encoding
        soup = BeautifulSoup(response.text, "html.parser")
        attachment_urls: list[str] = []
        for link in soup.find_all("a", href=True):
            href = urljoin(announcement.announcement_url, str(link.get("href")))
            path = href.lower().split("?", 1)[0]
            if path.endswith((".pdf", ".hwpx", ".hwp")) and href not in attachment_urls:
                attachment_urls.append(href)
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        attachments = []
        extracted_parts = [text]
        for attachment_url in attachment_urls[:5]:
            try:
                extracted, kind = _attachment_text(attachment_url, self.timeout_seconds)
                attachments.append({"url": attachment_url, "type": kind, "extracted": bool(extracted)})
                if extracted:
                    extracted_parts.append(extracted)
            except (requests.RequestException, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
                attachments.append({"url": attachment_url, "type": "failed", "extracted": False})
        text = re.sub(r"\s+", " ", " ".join(extracted_parts)).strip()
        maximum = 30000
        return {
            "notice_id": notice_id,
            "title": announcement.title,
            "url": announcement.announcement_url,
            "text": text[:maximum],
            "char_count": len(text),
            "truncated": len(text) > maximum,
            "sections": _section_windows(text),
            "attachments": attachments,
            "source": "direct_html_extraction",
            "disclaimer": "자동 추출 결과이므로 첨부 공고문과 기관 원문을 함께 확인해주세요.",
        }

    def competition(self, announcement_id: str, history: bool = True) -> dict[str, Any]:
        del history
        announcement = self.source.lookup(announcement_id)
        if announcement is None:
            raise SourceError("직접 수집 캐시에서 공고를 찾지 못했습니다.")
        payload = announcement.to_dict()
        payload.update(announcement.metadata)
        if announcement.source_id.startswith("apt_"):
            pblanc_no = announcement.source_id.removeprefix("apt_")
            try:
                response = requests.get(
                    "https://www.applyhome.co.kr/ai/aib/forSaleNmFirstPriority.do",
                    params={"pblancNo": pblanc_no}, timeout=self.timeout_seconds,
                    headers={"User-Agent": "Mozilla/5.0 youth-housing-compass"},
                )
                response.raise_for_status()
                rates = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*:\s*1", response.text)]
                if rates:
                    return {
                        "announcement_id": announcement_id,
                        "competition_rate": round(sum(rates) / len(rates), 1),
                        "source": "applyhome_result_page",
                        "disclaimer": "청약홈 결과 페이지 자동 추출값이며 세부 주택형별 결과를 확인해주세요.",
                    }
            except requests.RequestException:
                pass
        return {"announcement_id": announcement_id, **competition_estimate(payload)}

    def changes(self, since: str = "", change_type: str = "", limit: int = 50) -> dict[str, Any]:
        self.source.fetch()
        return self.source.tracker.query(since, change_type, limit)

    def calendar(self, announcement_id: str) -> BinaryResponse:
        announcement = self.source.lookup(announcement_id)
        if announcement is None:
            raise SourceError("직접 수집 캐시에서 공고를 찾지 못했습니다.")
        raw_start = announcement.apply_start or str(announcement.metadata.get("notice_date") or "")
        raw_end = announcement.apply_end or raw_start
        try:
            start = datetime.fromisoformat(raw_start).date()
            end = datetime.fromisoformat(raw_end).date() + timedelta(days=1)
        except ValueError as error:
            raise SourceError("확정된 일정이 없어 캘린더 파일을 만들 수 없습니다.") from error
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        body = "\r\n".join((
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Youth Housing Compass//KO",
            "BEGIN:VEVENT", f"UID:{_escape_ics(announcement.source_id)}@youth-housing-compass",
            f"DTSTAMP:{now}", f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}", f"SUMMARY:{_escape_ics(announcement.title)}",
            f"DESCRIPTION:{_escape_ics('신청 전 기관 원문에서 일정을 다시 확인해주세요.')}",
            f"URL:{_escape_ics(announcement.announcement_url)}", "END:VEVENT", "END:VCALENDAR", "",
        ))
        return BinaryResponse(body.encode("utf-8"), "text/calendar")
