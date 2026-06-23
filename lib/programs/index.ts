import samplePrograms from "@/data/housing_programs.json";
import liveSnapshot from "@/data/live_housing_programs.json";
import { fetchAnnouncementApi, getAnnouncementApiBaseUrl } from "../announcement-api";
import type { ApplicationStatus, HousingProgram } from "../types";

type AnnouncementApiItem = {
  id: string;
  source_id: string;
  title: string;
  organization: string;
  source_type: string;
  category: string;
  total_units: number | null;
  region: string;
  district: string;
  housing_type: string;
  target: string[];
  apply_start: string;
  apply_end: string;
  status: ApplicationStatus;
  announcement_url: string;
  summary: string;
  eligibility_summary: string;
  benefit_summary: string;
  required_documents: string[];
  age_min: number | null;
  age_max: number | null;
  homeless_required: boolean | null;
  income_condition: string;
  metadata?: {
    analysis_quality?: "high" | "medium" | "low" | "failed";
    analysis_source?: string;
  };
};

type AnnouncementApiResponse = {
  announcements: AnnouncementApiItem[];
};

export type ProgramLoadResult = {
  programs: HousingProgram[];
  dataSource: "live" | "snapshot" | "sample";
  warning?: string;
};

type LiveSnapshot = {
  generated_at?: string;
  announcements?: AnnouncementApiItem[];
};

function toHousingProgram(item: AnnouncementApiItem): HousingProgram {
  return {
    id: item.id,
    source_id: item.source_id,
    category: item.category,
    title: item.title,
    organization: item.organization,
    region: item.region,
    district: item.district,
    housing_type: item.housing_type || item.category,
    target: item.target,
    age_min: item.age_min,
    age_max: item.age_max,
    homeless_required: item.homeless_required,
    income_condition: item.income_condition,
    apply_start: item.apply_start,
    apply_end: item.apply_end,
    status: item.status,
    announcement_url: item.announcement_url,
    summary: item.summary,
    eligibility_summary: item.eligibility_summary,
    benefit_summary: item.benefit_summary,
    required_documents: item.required_documents,
    source_type: item.source_type,
    total_units: item.total_units,
    analysis_quality: item.metadata?.analysis_quality
  };
}

function isPublicRecruitmentNotice(item: AnnouncementApiItem) {
  const title = item.title ?? "";
  const housingType = item.housing_type ?? "";
  const included = /(입주자\s*모집|예비입주자\s*모집|모집\s*공고|공급\s*공고|본청약)/.test(title);
  const excluded = /(접수\s*(결과|현황)|신청\s*현황|청약\s*(신청\s*)?경쟁률|경쟁률\s*(게시|공지)|당첨자|발표|선정\s*결과|개찰\s*결과|추첨\s*결과|서류\s*심사|자격\s*심사|입주\s*대상자|계약\s*(체결|결과)|결과\s*알림|동호표|마감\s*안내|민영\s*주택)/.test(title);
  const nonHousing = /(용지|상가|산업시설|업무시설|유치원)/.test(`${title} ${housingType}`);
  return ["LH", "SH", "GH"].includes(item.organization) && included && !excluded && !nonHousing;
}

function mergeLiveWithAnalyzedSnapshot(
  liveItems: AnnouncementApiItem[],
  snapshotItems: AnnouncementApiItem[]
) {
  const analyzed = new Map(
    snapshotItems
      .filter((item) => item.metadata?.analysis_source === "official_notice_and_attachments")
      .map((item) => [item.source_id, item])
  );
  const merged = new Map<string, AnnouncementApiItem>();
  for (const item of liveItems) {
    const stored = analyzed.get(item.source_id);
    merged.set(item.source_id, stored ? { ...item, ...stored } : item);
  }
  for (const item of snapshotItems) {
    if (!merged.has(item.source_id)) merged.set(item.source_id, item);
  }
  return [...merged.values()].filter(isPublicRecruitmentNotice);
}

export async function loadHousingPrograms(): Promise<ProgramLoadResult> {
  const baseUrl = getAnnouncementApiBaseUrl();
  const storedSnapshot = liveSnapshot as unknown as LiveSnapshot;
  const snapshotItems = Array.isArray(storedSnapshot.announcements)
    ? storedSnapshot.announcements.filter(isPublicRecruitmentNotice)
    : [];
  // GitHub Actions가 매일 검증·커밋한 스냅샷을 우선 사용합니다.
  // 무료 Render의 절전 복구를 기다리지 않아 공모전 시연이 즉시 응답합니다.
  if (snapshotItems.length) {
    return {
      programs: snapshotItems.map(toHousingProgram),
      dataSource: "snapshot"
    };
  }
  if (!baseUrl) {
    return { programs: samplePrograms as HousingProgram[], dataSource: "sample" };
  }

  try {
    const response = await fetchAnnouncementApi("/v1/announcements", {
      headers: { Accept: "application/json" }
    });

    if (!response.ok) {
      throw new Error(`공고 서비스가 ${response.status} 상태로 응답했습니다.`);
    }

    const payload = (await response.json()) as AnnouncementApiResponse;
    if (!Array.isArray(payload.announcements) || !payload.announcements.length) {
      throw new Error("공고 서비스 응답 형식이 올바르지 않습니다.");
    }

    return {
      programs: mergeLiveWithAnalyzedSnapshot(
        payload.announcements,
        snapshotItems
      ).map(toHousingProgram),
      dataSource: "live"
    };
  } catch (error) {
    if (snapshotItems.length) {
      const generatedAt = storedSnapshot.generated_at
        ? new Date(storedSnapshot.generated_at).toLocaleString("ko-KR", {
            timeZone: "Asia/Seoul"
          })
        : "최근";
      return {
        programs: snapshotItems.map(toHousingProgram),
        dataSource: "snapshot",
        warning: `실시간 공고 연결이 불안정해 ${generatedAt} 저장된 실공고를 표시합니다.`
      };
    }
    return {
      programs: samplePrograms as HousingProgram[],
      dataSource: "sample",
      warning: `실공고를 불러오지 못해 출품용 샘플 공고를 표시합니다. ${
        error instanceof Error ? error.message : "공고 서비스 연결을 확인해주세요."
      }`
    };
  }
}
