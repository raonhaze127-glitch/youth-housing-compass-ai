export type HousingProgram = {
  id: string;
  source_id?: string;
  category?: string;
  title: string;
  organization: string;
  region: string;
  district: string;
  housing_type: string;
  target: string[];
  age_min: number | null;
  age_max: number | null;
  homeless_required: boolean | null;
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
  total_units?: number | null;
  analysis_quality?: "high" | "medium" | "low" | "failed";
};

export type ApplicationStatus = "open" | "planned" | "closed" | "unknown";

export type UserProfile = {
  region?: string;
  district?: string;
  age?: number;
  homeless?: boolean;
  incomeLevel?: "low" | "middle" | "high" | "unknown";
  householdType?: "youth" | "newlywed" | "unknown";
  children?: Array<{ age: number }>;
  interests: string[];
  rawText: string;
};

export type Recommendation = HousingProgram & {
  status: ApplicationStatus;
  score: number;
  reasons: string[];
};
