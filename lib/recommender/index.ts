import {
  isClearlyIneligible,
  matchProgram,
  matchesProgramDistrict
} from "../matcher";
import { SEOUL_DISTRICTS } from "../parser";
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

function isExplicitlyBroadProgram(profile: UserProfile, program: HousingProgram) {
  const text = [program.title, program.summary, ...program.target].join(" ");
  if (program.region === "전국") return /전국|전\s*지역/.test(text);
  return program.region === profile.region && /전역|전체\s*지역/.test(text);
}

function mentionsAnotherSeoulDistrict(profile: UserProfile, program: HousingProgram) {
  if (profile.region !== "서울" || !profile.district) return false;
  const text = [program.title, program.summary, ...program.target].join(" ");
  return SEOUL_DISTRICTS.some(
    (district) => district !== profile.district && text.includes(district)
  );
}

export function recommendPrograms(
  profile: UserProfile,
  programs: HousingProgram[],
  limit?: number,
  now = new Date()
): Recommendation[] {
  const regionEligiblePrograms = profile.region
    ? programs.filter(
        (program) =>
          program.region === profile.region ||
          (program.region === "전국" &&
            (isExplicitlyBroadProgram(profile, program) ||
              Boolean(profile.district && matchesProgramDistrict(program, profile.district))))
      )
    : programs;
  const eligiblePrograms = regionEligiblePrograms
    .filter(
      (program) =>
        !profile.district ||
        matchesProgramDistrict(program, profile.district) ||
        (program.region === "서울" &&
          !program.district &&
          !mentionsAnotherSeoulDistrict(profile, program)) ||
        isExplicitlyBroadProgram(profile, program)
    )
    .filter((program) => !isClearlyIneligible(profile, program));
  const recommendations = eligiblePrograms
    .map((program) => matchProgram(profile, program, getApplicationStatus(program, now)))
    .sort((a, b) => {
      const statusDifference = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
      return statusDifference || b.score - a.score;
    });

  return limit === undefined ? recommendations : recommendations.slice(0, limit);
}
