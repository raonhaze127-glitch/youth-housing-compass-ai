import { matchProgram } from "../matcher";
import { getApplicationStatus } from "../status";
import type {
  ApplicationStatus,
  HousingProgram,
  Recommendation,
  UserProfile
} from "../types";

const STATUS_ORDER: Record<ApplicationStatus, number> = {
  open: 0,
  planned: 1,
  unknown: 2,
  closed: 3
};

export function recommendPrograms(
  profile: UserProfile,
  programs: HousingProgram[],
  limit?: number,
  now = new Date()
): Recommendation[] {
  const recommendations = programs
    .map((program) => matchProgram(profile, program, getApplicationStatus(program, now)))
    .sort((a, b) => {
      const statusDifference = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
      return statusDifference || b.score - a.score;
    });

  return limit === undefined ? recommendations : recommendations.slice(0, limit);
}
