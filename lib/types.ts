export type HousingProgram = {
  id: string;
  title: string;
  organization: string;
  source: string;
  region: string;
  district: string;
  target: string[];
  age_min: number;
  age_max: number;
  income_condition: string;
  homeless_required: boolean;
  benefit_type: string;
  benefit_summary: string;
  apply_start: string;
  apply_end: string;
  required_documents: string[];
  summary: string;
  url: string;
  status: "open" | "closed" | "planned";
};

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
  score: number;
  reasons: string[];
};
