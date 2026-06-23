import {
  isClearlyIneligible,
  matchProgram,
  matchesProgramDistrict
} from "../matcher";
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
  const regionEligiblePrograms = profile.region
    ? programs.filter(
        (program) => program.region === profile.region || program.region === "전국"
      )
    : programs;
  const eligiblePrograms = regionEligiblePrograms
    .filter((program) => !profile.district || !program.district || program.district === profile.district)
    .filter((program) => !isClearlyIneligible(profile, program));
  const districtMatches = profile.district
    ? eligiblePrograms.filter((program) => matchesProgramDistrict(program, profile.district!))
    : [];
  const scopedPrograms = districtMatches.length ? districtMatches : eligiblePrograms;
  const recommendations = scopedPrograms
    .map((program) => matchProgram(profile, program, getApplicationStatus(program, now)))
    .sort((a, b) => {
      const statusDifference = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
      return statusDifference || b.score - a.score;
    });

  return limit === undefined ? recommendations : recommendations.slice(0, limit);
}
