import { fetchAnnouncementApi } from "../announcement-api";
import type { ApplicationStatus, Recommendation, UserProfile } from "../types";

const STATUS_ORDER: Record<ApplicationStatus, number> = {
  open: 0,
  planned: 1,
  unknown: 2,
  closed: 3
};

function preferredCategories(profile: UserProfile) {
  const result = new Set<string>();
  for (const interest of profile.interests) {
    if (interest === "월세") {
      result.add("오피스텔/도시형");
      result.add("공공지원민간임대");
    }
    if (interest === "전세" || interest === "공공임대") {
      result.add("LH공공분양");
      result.add("SH 공공주택");
      result.add("GH 공공주택");
    }
    if (interest === "공공임대") result.add("APT");
  }
  return [...result];
}

export async function applyLiveMatches(
  profile: UserProfile,
  recommendations: Recommendation[]
) {
  const live = recommendations.filter((item) => item.source_type === "k_apt_alert_proxy");
  if (!live.length) return recommendations;

  try {
    const response = await fetchAnnouncementApi("/v1/announcements/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile: {
          preferred_categories: preferredCategories(profile),
          preferred_regions: profile.region ? [profile.region] : [],
          min_units: 0
        },
        announcements: live.map((item) => ({
          id: item.source_id ?? item.id,
          house_category: item.category ?? item.housing_type,
          region: item.region,
          total_units: item.total_units ?? 0
        }))
      })
    });
    if (!response.ok) return recommendations;
    const payload = (await response.json()) as {
      matches?: Array<{ id: string; fit_level: "high" | "medium" | "low" }>;
    };
    const matches = new Map(payload.matches?.map((item) => [item.id, item.fit_level]) ?? []);

    return recommendations
      .map((item) => {
        const level = matches.get(item.source_id ?? item.id);
        if (!level) return item;
        const bonus = level === "high" ? 20 : level === "medium" ? 8 : 0;
        return {
          ...item,
          score: item.score + bonus,
          reasons: [
            `실공고 프로필 적합도는 ${level === "high" ? "높음" : level === "medium" ? "보통" : "낮음"}입니다.`,
            ...item.reasons
          ]
        };
      })
      .sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || b.score - a.score);
  } catch {
    return recommendations;
  }
}
