import type {
  ApplicationStatus,
  HousingProgram,
  Recommendation,
  UserProfile
} from "../types";

function matchesRegion(profile: UserProfile, program: HousingProgram) {
  if (!profile.region) return false;
  return program.region === profile.region || program.region === "전국";
}

function matchesInterest(profile: UserProfile, program: HousingProgram) {
  return profile.interests.some((interest) => {
    return program.housing_type.includes(interest) || program.target.includes(interest);
  });
}

function hasIncomeCondition(program: HousingProgram) {
  return /소득|중위소득|자산|재산/.test(program.income_condition);
}

export function matchProgram(
  profile: UserProfile,
  program: HousingProgram,
  status: ApplicationStatus
): Recommendation {
  const reasons: string[] = [];
  let score = 0;

  if (
    profile.age &&
    program.age_min !== null &&
    program.age_max !== null &&
    profile.age >= program.age_min &&
    profile.age <= program.age_max
  ) {
    score += 30;
    reasons.push(`만 ${profile.age}세가 지원 연령 범위에 들어갑니다.`);
  }

  if (matchesRegion(profile, program)) {
    score += 25;
    reasons.push(
      program.region === "전국"
        ? "전국 단위 사업이라 현재 지역에서도 검토할 수 있습니다."
        : `${profile.region} 지역 조건과 맞습니다.`
    );
  }

  if (profile.homeless === true && program.homeless_required === true) {
    score += 20;
    reasons.push("무주택 조건이 필요한 사업과 입력 조건이 맞습니다.");
  }

  if (profile.householdType === "youth" && program.target.includes("청년")) {
    score += 15;
    reasons.push("청년 대상 사업입니다.");
  }

  if (profile.householdType === "newlywed" && program.target.includes("신혼부부")) {
    score += 15;
    reasons.push("신혼부부 대상 사업입니다.");
  }

  if (matchesInterest(profile, program)) {
    score += 15;
    reasons.push(`${program.housing_type} 수요와 관련이 높습니다.`);
  }

  if (profile.incomeLevel === "low" && hasIncomeCondition(program)) {
    score += 8;
    reasons.push("소득 기준 확인이 필요한 사업이며, 낮은 소득 구간이라 우선 검토할 만합니다.");
  } else if (profile.incomeLevel === "middle" && hasIncomeCondition(program)) {
    score += 4;
    reasons.push("소득 및 자산 기준은 공고문 기준으로 추가 확인이 필요합니다.");
  } else if (profile.incomeLevel === "high" && hasIncomeCondition(program)) {
    reasons.push("소득 기준 초과 가능성이 있어 공고문 세부 기준 확인이 필요합니다.");
  }

  if (status === "open") {
    score += 10;
    reasons.push("현재 접수 중인 사업입니다.");
  } else if (status === "planned") {
    score += 4;
    reasons.push(`${program.apply_start}부터 접수가 시작될 예정입니다.`);
  } else if (status === "closed") {
    score -= 20;
    reasons.push("접수가 마감되어 다음 모집 공고를 확인해야 합니다.");
  } else {
    reasons.push("신청기간이 확인되지 않아 원문 일정 확인이 필요합니다.");
  }

  if (score === 0) {
    reasons.push("입력 조건이 부족해 기본 후보로만 표시됩니다.");
  }

  return {
    ...program,
    status,
    score,
    reasons
  };
}
