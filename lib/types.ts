export type HousingProgram = {
  id: string;
  title: string;
  organization: string;
  region: string;
  district: string;
  housing_type: string;
  target: string[];
  age_min: number;
  age_max: number;
  homeless_required: boolean;
  income_condition: string;
  apply_start: string;
  apply_end: string;
  status: ApplicationStatus;
  announcement_url: string;
  summary: string;
  eligibility_summary: string;
  benefit_summary: string;
  required_documents: string[];
  source_type: string;
};

export type ApplicationStatus = "open" | "planned" | "closed";

export type UserProfile = {
  region?: string;
  district?: string;
  age?: number;
  homeless?: boolean;
  incomeLevel?: "low" | "middle" | "high" | "unknown";
  householdType?: "youth" | "newlywed" | "unknown";
  interests: string[];
  rawText: string;
};

export type Recommendation = HousingProgram & {
  status: ApplicationStatus;
  score: number;
  reasons: string[];
};
