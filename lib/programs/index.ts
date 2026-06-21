import samplePrograms from "@/data/housing_programs.json";
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
};

type AnnouncementApiResponse = {
  announcements: AnnouncementApiItem[];
};

export type ProgramLoadResult = {
  programs: HousingProgram[];
  dataSource: "live" | "sample";
  warning?: string;
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
    total_units: item.total_units
  };
}

export async function loadHousingPrograms(): Promise<ProgramLoadResult> {
  const baseUrl = getAnnouncementApiBaseUrl();
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
    if (!Array.isArray(payload.announcements)) {
      throw new Error("공고 서비스 응답 형식이 올바르지 않습니다.");
    }

    return {
      programs: payload.announcements.map(toHousingProgram),
      dataSource: "live"
    };
  } catch (error) {
    return {
      programs: samplePrograms as HousingProgram[],
      dataSource: "sample",
      warning: `실공고를 불러오지 못해 출품용 샘플 공고를 표시합니다. ${
        error instanceof Error ? error.message : "공고 서비스 연결을 확인해주세요."
      }`
    };
  }
}
