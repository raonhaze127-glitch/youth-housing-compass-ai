from __future__ import annotations

from datetime import date
from typing import Any


def _number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _score_no_house(years: float) -> int:
    if years < 0:
        return 0
    return 2 if years < 1 else min(32, 2 + int(years) * 2)


def _score_family(count: int) -> int:
    return min(35, 5 + max(0, count) * 5)


def _score_account(years: float) -> int:
    if years < 0.5:
        return 1
    if years < 1:
        return 2
    return min(17, int(years) + 2)


def _account_years(profile: dict[str, Any]) -> float:
    account = profile.get("subscription_account") or {}
    total = _number(account.get("years"))
    pre = _number(account.get("minor_years_pre_2024"))
    post = _number(account.get("minor_years_post_2024"))
    return max(0.0, total - max(0.0, pre - 2.0) - max(0.0, post - 5.0))


def _special(profile: dict[str, Any], kind: str) -> dict[str, Any]:
    no_house = profile.get("no_house", True) is not False
    account_years = _number((profile.get("subscription_account") or {}).get("years"))
    if kind == "신혼부부":
        raw = str(profile.get("marriage_date") or "")
        if not no_house:
            return {"eligible": False, "reason": "현재 무주택 요건을 확인해주세요."}
        try:
            married = date.fromisoformat(raw)
            elapsed = (date.today() - married).days / 365.25
            return {
                "eligible": elapsed <= 7,
                "reason": f"혼인 기간 {elapsed:.1f}년 기준 사전 점검",
            }
        except ValueError:
            return {"eligible": False, "reason": "혼인신고일 확인이 필요합니다."}
    if kind == "생애최초":
        ok = no_house and not bool(profile.get("ever_owned_house")) and account_years >= 2
        return {"eligible": ok, "reason": "무주택·주택소유 이력·통장 2년 기준 사전 점검"}
    if kind == "다자녀":
        minors = sum(1 for child in profile.get("children", []) if _number(child.get("age"), 99) < 19)
        return {"eligible": minors >= 2, "reason": f"미성년 자녀 {minors}명 기준"}
    if kind == "노부모부양":
        ok = bool(profile.get("dependent_parents_3y"))
        return {"eligible": ok, "reason": "65세 이상 직계존속 3년 동거 여부 기준"}
    age = int(_number(profile.get("age"), 99))
    return {"eligible": 19 <= age <= 39 and no_house, "reason": f"만 {age}세·무주택 기준"}


def score_payload(payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("profile") or {}
    adjusted = _account_years(profile)
    scores = {
        "no_house": _score_no_house(_number(profile.get("no_house_years"))),
        "family": _score_family(int(_number(profile.get("dependents")))),
        "account": _score_account(adjusted),
        "account_adjusted_years": adjusted,
        "max_total": 84,
    }
    scores["total"] = scores["no_house"] + scores["family"] + scores["account"]
    specials = {kind: _special(profile, kind) for kind in ("신혼부부", "생애최초", "다자녀", "노부모부양", "청년")}
    account = profile.get("subscription_account") or {}
    region = str((payload.get("announcement") or {}).get("region") or profile.get("region") or "")
    required = 12 if region in {"서울", "경기", "인천"} else 6
    user_count = int(_number(account.get("deposit_count")))
    return {
        "scores": scores,
        "specials": specials,
        "first_priority": {
            "eligible": user_count >= required and profile.get("previous_win") != "5년이내",
            "required_count": required,
            "user_count": user_count,
            "reason": f"납입 {user_count}회 / 기준 {required}회",
            "warnings": ["거주기간과 세대구성원 요건은 공고 원문 확인이 필요합니다."],
        },
        "disclaimer": "사전 점검 결과이며 실제 신청 자격을 확정하지 않습니다.",
    }


def match_payload(payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("profile") or {}
    regions = set(profile.get("preferred_regions") or [])
    categories = set(profile.get("preferred_categories") or [])
    minimum = int(_number(profile.get("min_units")))
    matches = []
    for announcement in payload.get("announcements") or []:
        score = 0
        reasons: list[str] = []
        if not regions or announcement.get("region") in regions or announcement.get("region") == "전국":
            score += 45
            reasons.append("희망 지역과 일치합니다.")
        if not categories or announcement.get("house_category") in categories:
            score += 35
            reasons.append("관심 주거 유형과 일치합니다.")
        units = int(_number(announcement.get("total_units")))
        if not minimum or units >= minimum:
            score += 20
        level = "high" if score >= 80 else "medium" if score >= 45 else "low"
        matches.append({"id": str(announcement.get("id") or ""), "fit_level": level, "score": score, "reasons": reasons})
    return {"matches": matches, "source": "direct_rule_engine"}


def competition_estimate(announcement: dict[str, Any]) -> dict[str, Any]:
    region = str(announcement.get("region") or "기타")
    size = str(announcement.get("size") or "중형")
    table = {
        "서울": {"소형": (85, 59), "중형": (45, 53), "대형": (18, None)},
        "경기": {"소형": (28, 43), "중형": (16, 36), "대형": (7, None)},
        "인천": {"소형": (18, 36), "중형": (9, 28), "대형": (5, None)},
    }
    bucket = "소형" if "소형" in size else "대형" if "대형" in size else "중형"
    rate, cutoff = table.get(region, {}).get(bucket, (5, 20))
    return {
        "avg_rate": rate,
        "avg_cutoff_score": cutoff,
        "source": "statistical_estimate",
        "disclaimer": "지역·면적 과거 통계 기반 참고치이며 실제 경쟁률이 아닙니다.",
    }
