from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .sources import SourceError


@dataclass(frozen=True)
class BinaryResponse:
    content: bytes
    content_type: str


class KAptAlertClient:
    def __init__(self, base_url: str, timeout_seconds: int = 180):
        if not base_url:
            raise ValueError("K_APT_ALERT_API_BASE_URL이 필요합니다.")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> BinaryResponse:
        url = f"{self.base_url}{path}"
        if query:
            clean_query = {
                key: value
                for key, value in query.items()
                if value is not None and value != ""
            }
            if clean_query:
                url = f"{url}?{urlencode(clean_query)}"

        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "User-Agent": "youth-housing-compass/0.1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return BinaryResponse(
                    content=response.read(),
                    content_type=response.headers.get_content_type(),
                )
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise SourceError(
                f"외부 공고 API가 {error.code} 상태로 응답했습니다: {detail[:300]}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise SourceError(f"외부 공고 API 요청에 실패했습니다: {error}") from error

    def json_request(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._request(method, path, query, payload)
        try:
            result = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceError("외부 공고 API JSON 응답을 해석하지 못했습니다.") from error
        if not isinstance(result, dict):
            raise SourceError("외부 공고 API 응답이 JSON 객체가 아닙니다.")
        return result

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.json_request("POST", "/v1/apt/score", payload=payload)

    def match(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.json_request("POST", "/v1/apt/match", payload=payload)

    def notice_raw(self, notice_id: str, force_refresh: bool = False) -> dict[str, Any]:
        safe_id = quote(notice_id, safe="")
        return self.json_request(
            "GET",
            f"/v1/apt/notice/{safe_id}/raw",
            query={"force_refresh": str(force_refresh).lower()},
        )

    def competition(self, announcement_id: str, history: bool = True) -> dict[str, Any]:
        safe_id = quote(announcement_id, safe="")
        return self.json_request(
            "GET",
            f"/v1/apt/announcements/{safe_id}/competition",
            query={"history": str(history).lower()},
        )

    def changes(
        self,
        since: str = "",
        change_type: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        return self.json_request(
            "GET",
            "/v1/apt/changes",
            query={"since": since, "change_type": change_type, "limit": limit},
        )

    def calendar(self, announcement_id: str) -> BinaryResponse:
        safe_id = quote(announcement_id, safe="")
        return self._request(
            "GET",
            f"/v1/apt/announcements/{safe_id}/ics",
        )
