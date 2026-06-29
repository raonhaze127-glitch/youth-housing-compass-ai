import type { Recommendation, UserProfile } from "../types";

export type AgentId =
  | "orchestrator"
  | "policy-agent"
  | "eligibility-agent"
  | "announcement-agent"
  | "recommendation-agent"
  | "verification-agent";

export type ConsultationIntent =
  | "policy"
  | "eligibility"
  | "announcement"
  | "recommendation"
  | "unsupported";

export type VerificationResult = {
  status: "pass" | "revise" | "block";
  checks: string[];
};

export type AgentAnswer = {
  answer: string;
  intent: ConsultationIntent;
  handledBy: AgentId;
  handledByLabel: string;
  agentTrace: AgentId[];
  verification: VerificationResult;
};

const AGENT_LABELS: Record<AgentId, string> = {
  orchestrator: "상담 조정 Agent",
  "policy-agent": "정책 설명 Agent",
  "eligibility-agent": "자격 진단 Agent",
  "announcement-agent": "공고 해석 Agent",
  "recommendation-agent": "추천 Agent",
  "verification-agent": "검증 Agent"
};

const HOUSING_TERMS =
  /공공주택|공공임대|공공분양|통합공공임대|영구임대|국민임대|행복주택|장기전세|매입임대|전세임대|분양전환/;

export function classifyConsultationIntent(message: string): ConsultationIntent {
  const normalized = message.trim();
  const hasPolicyForm = /뜻|의미|정의|종류|차이|뭐야|무엇|설명|알려줘/.test(normalized);
  const hasExplicitEligibilityQuestion =
    /자격|신청\s*가능|가능해|될까|소득|자산|청약통장|가점|순위/.test(normalized);
  const hasProfileConditions =
    /무주택|청년|신혼|자녀/.test(normalized) && /\d{2}\s*(?:세|살|만)/.test(normalized);
  const looksLikeProfileSearch =
    /(서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주|[가-힣]+시|[가-힣]+군|[가-힣]+구).*(무주택|청년|신혼|자녀|[0-9]{2}\s*세)|무주택.*(서울|경기|[가-힣]+시|[가-힣]+군|[가-힣]+구)/.test(
      normalized
    ) || hasProfileConditions;

  if (HOUSING_TERMS.test(normalized) && hasPolicyForm && !/\d+\s*번/.test(normalized)) {
    return "policy";
  }
  if (/\d+\s*번/.test(normalized) || /서류|준비물|신청기간|일정|언제|마감|임대료|보증금|원문|링크|경쟁률/.test(normalized)) {
    if (/자격|신청\s*가능|소득|자산|무주택|나이|연령|청약통장|가점|순위/.test(normalized)) {
      return "eligibility";
    }
    return "announcement";
  }
  if (/추천|찾아|찾고|공고\s*(?:알려|추천|검색)|어떤\s*(?:집|주택)|우선\s*검토|주택을\s*알아|지원.*찾/.test(normalized)) {
    return "recommendation";
  }
  if (looksLikeProfileSearch && !hasExplicitEligibilityQuestion) {
    return "recommendation";
  }
  if (/자격|신청\s*가능|소득|자산|무주택|나이|연령|청약통장|가점|순위/.test(normalized)) {
    return "eligibility";
  }
  if (/거주|살고|월세|전세/.test(normalized)) return "recommendation";
  return "unsupported";
}

function selectProgram(
  message: string,
  recommendations: Recommendation[],
  contextProgramIds: string[]
) {
  const rank = message.match(/([1-9])\s*번/);
  if (rank) {
    const id = contextProgramIds[Number(rank[1]) - 1];
    return recommendations.find((item) => item.id === id);
  }
  return recommendations.find(
    (program) => program.title.length >= 4 && message.includes(program.title)
  );
}

function policyAnswer(message: string) {
  if (/공공주택/.test(message) && /공공임대/.test(message)) {
    return "공공주택은 공공주택사업자가 공급하는 주택의 상위 개념이고, 공공임대주택은 그중 임대차계약으로 거주하는 주택입니다. 공공주택에는 공공분양주택도 포함되므로 공고를 볼 때 임대인지 분양인지 먼저 구분해야 합니다.";
  }
  if (/공공임대/.test(message) && /공공분양/.test(message)) {
    return "공공임대는 보증금과 임대료를 내고 일정 기간 거주하는 방식이고, 공공분양은 분양대금을 부담하고 소유권을 취득하는 방식입니다. 분양전환공공임대는 임대 후 분양전환을 검토한다는 점에서 두 성격이 이어집니다.";
  }
  if (/종류/.test(message) || /차이/.test(message)) {
    return "대표 공공임대 유형에는 통합공공임대, 영구임대, 국민임대, 행복주택, 장기전세, 매입임대, 전세임대, 분양전환공공임대가 있습니다. 대상계층, 임대기간, 소득·자산 기준과 선정방식이 다르므로 관심 유형을 말씀해주시면 차이를 좁혀 설명할 수 있습니다.";
  }
  if (/행복주택/.test(message)) {
    return "행복주택은 대학생·청년·신혼부부 등 생애 초기 계층과 고령자·주거급여수급자 등을 대상으로 하는 공공임대입니다. 계층마다 소득·자산 기준과 최대 거주기간이 달라 해당 모집공고 확인이 필요합니다.";
  }
  if (/국민임대/.test(message)) {
    return "국민임대는 무주택 저소득 가구의 장기 주거안정을 위한 공공임대입니다. 소득·자산, 가구원 수, 공급면적과 지역순위 기준을 함께 확인해야 합니다.";
  }
  return "공공임대는 정부·지방자치단체·LH·지방공사 등이 주거안정을 위해 공급하는 임대주택입니다. 유형별 대상과 심사 방식이 다르므로 궁금한 주택 유형을 함께 알려주세요.";
}

function missingProfileFields(profile: UserProfile) {
  return [
    profile.region ? "" : "거주·희망 지역",
    profile.age === undefined ? "만 나이 또는 생년월일" : "",
    profile.homeless === undefined ? "무주택 여부" : "",
    profile.incomeLevel === "unknown" ? "가구원 수와 정확한 소득" : "",
    "총자산·자동차 가액"
  ].filter(Boolean);
}

function eligibilityAnswer(
  message: string,
  profile: UserProfile,
  selected?: Recommendation
) {
  if (/가점/.test(message)) {
    return selected
      ? `${selected.title}은 공고 유형과 일반·우선·특별공급 구분, 선정방식이 확인된 뒤에만 가점을 계산할 수 있습니다. 현재 추천 데이터만으로는 공식 배점표를 확정할 수 없어 점수 계산을 보류합니다.`
      : "가점은 특정 공고의 주택 유형과 공급 유형, 선정방식이 확인된 뒤에만 계산할 수 있습니다. 순위제 공고라면 가점 대신 적용 순위와 동순위 기준을 안내합니다. 공고 번호나 제목을 알려주세요.";
  }

  if (/순위/.test(message) && !selected) {
    return "순위는 주택 유형과 공급면적에 따라 지역, 거주기간, 청약통장 가입·납입 조건 등이 다릅니다. 확인할 공고 제목이나 번호를 알려주시면 가점과 혼동하지 않고 순위 기준을 설명하겠습니다.";
  }

  if (selected) {
    const known = selected.eligibility_summary || selected.reasons.join(" ");
    return `${selected.title}의 사전 자격 진단입니다. ${known} 현재 입력값 기준으로는 참고 판정만 가능하며, 소득·자산·세대구성의 정확한 값과 공고 원문 예외조항을 추가 확인해야 합니다.`;
  }

  const missing = missingProfileFields(profile);
  const known = [
    profile.region ? `${profile.region}${profile.district ? ` ${profile.district}` : ""} 거주` : "",
    profile.age !== undefined ? `만 ${profile.age}세` : "",
    profile.homeless === true ? "무주택" : profile.homeless === false ? "주택 보유" : ""
  ].filter(Boolean);
  return `현재 확인된 조건은 ${known.length ? known.join(", ") : "아직 충분하지 않습니다"}. 정확한 자격 진단에는 ${missing.join(", ")}와 특정 모집공고가 필요합니다. 먼저 관심 공고나 주택 유형을 알려주세요.`;
}

function announcementAnswer(message: string, selected?: Recommendation) {
  if (!selected) {
    return "해석할 공고를 특정하지 못했습니다. 이전 추천의 번호, 공고 제목 또는 공식 URL을 알려주시면 자격·일정·서류·임대조건을 확인해드릴 수 있습니다.";
  }
  if (/서류|준비물/.test(message)) {
    return selected.required_documents.length
      ? `${selected.title}의 현재 구조화된 준비서류는 ${selected.required_documents.join(", ")}입니다. 신청자 유형에 따라 추가 서류가 있을 수 있습니다.`
      : `${selected.title}의 준비서류가 아직 구조화되지 않았습니다. 공식 원문 공고의 제출서류 표를 확인해야 합니다.`;
  }
  if (/기간|일정|언제|마감/.test(message)) {
    return selected.apply_start && selected.apply_end
      ? `${selected.title}의 신청기간은 ${selected.apply_start}부터 ${selected.apply_end}까지이며, 현재 상태는 ${selected.status === "open" ? "접수중" : selected.status === "planned" ? "모집예정" : selected.status === "closed" ? "마감" : "일정 확인 필요"}입니다.`
      : `${selected.title}의 신청기간은 구조화 데이터에서 확인되지 않았습니다. 공식 원문 일정 확인이 필요합니다.`;
  }
  if (/임대료|보증금/.test(message)) {
    return selected.benefit_summary
      ? `${selected.title}의 임대조건 요약입니다. ${selected.benefit_summary}`
      : `${selected.title}의 정확한 보증금·임대료가 구조화되지 않았습니다. 주택형별 임대조건 표를 공식 원문에서 확인해야 합니다.`;
  }
  if (/원문|링크/.test(message)) {
    return `${selected.title} 공식 원문: ${selected.announcement_url}`;
  }
  if (/경쟁률/.test(message)) {
    return `${selected.title}의 공식 경쟁률은 현재 상담 데이터에 연동되지 않았습니다. 공급기관의 모집결과 또는 경쟁률 공고를 확인해야 합니다.`;
  }
  return `${selected.title}은 ${selected.organization}의 ${selected.housing_type} 공고입니다. ${selected.summary} 자격, 준비서류, 신청기간, 임대조건 또는 원문 링크를 이어서 물어보실 수 있습니다.`;
}

function recommendationAnswer(recommendations: Recommendation[], profile: UserProfile) {
  if (!recommendations.length) {
    return "현재 조건으로 확인된 공고가 없습니다. 지역, 만 나이, 무주택 여부, 가구 유형과 원하는 주택 유형을 알려주시면 검색 범위를 다시 정리하겠습니다.";
  }
  const active = recommendations.filter((item) => item.status === "open").length;
  const planned = recommendations.filter((item) => item.status === "planned").length;
  const top = recommendations[0];
  const profileSummary = [
    profile.region ? `${profile.region}${profile.district ? ` ${profile.district}` : ""}` : "",
    profile.age !== undefined ? `만 ${profile.age}세` : "",
    profile.homeless === true ? "무주택" : profile.homeless === false ? "주택 보유" : "",
    profile.childrenCount ? `자녀 ${profile.childrenCount}명` : ""
  ].filter(Boolean);
  const reasons = top.reasons.slice(0, 3);
  const confirmationItems = [
    profile.incomeLevel === "unknown" ? "가구 월평균소득" : "",
    "총자산·자동차 가액",
    top.required_documents.length ? "" : "공식 공고문의 제출서류 표",
    top.apply_start && top.apply_end ? "" : "정확한 신청기간"
  ].filter(Boolean);
  const schedule = top.apply_start && top.apply_end
    ? `신청기간은 ${top.apply_start}부터 ${top.apply_end}까지입니다.`
    : "신청기간은 공식 원문에서 추가 확인이 필요합니다.";
  return `입력 조건${profileSummary.length ? `(${profileSummary.join(", ")})` : ""} 기준으로 우선 검토할 공고 ${recommendations.length}개를 찾았습니다. 접수중 ${active}개, 모집예정 ${planned}개입니다.

1순위로 볼 공고는 “${top.title}”입니다. ${schedule}

추천 근거는 ${reasons.length ? reasons.join(" ") : "입력 조건과 공고 조건의 관련성이 확인됐다는 점입니다."}

다음 확인이 필요합니다: ${confirmationItems.join(", ")}. 원문 확인 후에는 신청기간, 신청방법, 제출서류, 소득·자산 기준 순서로 점검하는 것이 좋습니다. 이는 당첨 예측이 아니라 검토 순서입니다.`;
}

function unsupportedAnswer() {
  return `제가 잘 이해하지 못했어요. 아래 예시처럼 질문해 주세요.

- 정책 설명: “행복주택과 국민임대의 차이가 뭐야?”
- 자격 진단: “만 29세 무주택 청년인데 신청할 수 있어?”
- 공고 해석: “2번 공고의 신청 기간과 준비 서류를 알려줘.”
- 공고 추천: “경기도에 거주하는 30세 무주택 청년에게 맞는 공고를 찾아줘.”

맞춤 추천을 원한다면 거주 지역, 나이, 무주택 여부, 가구원 수, 소득을 알려주세요.`;
}

function verifyAnswer(answer: string, intent: ConsultationIntent, selected?: Recommendation) {
  const forbidden = ["무조건 가능합니다", "당첨 확실합니다", "100% 됩니다", "문제 없습니다", "이 공고에 넣으면 됩니다"];
  let verified = answer;
  const checks = ["금지 표현 검사", "과도한 확신 검사"];
  let status: VerificationResult["status"] = "pass";

  for (const phrase of forbidden) {
    if (verified.includes(phrase)) {
      verified = verified.replaceAll(phrase, "입력값 기준 추가 검토가 필요합니다");
      status = "revise";
    }
  }
  if (["eligibility", "announcement", "recommendation"].includes(intent)) {
    const notice = " 최종 판단은 모집공고문 원문 기준으로 확인해야 합니다.";
    if (!verified.includes("모집공고문 원문 기준")) verified += notice;
    checks.push("공고 원문 확인 안내");
  }
  if (selected?.announcement_url) checks.push("공식 원문 URL 확인");
  return { answer: verified, verification: { status, checks } };
}

export function answerWithAgents(input: {
  message: string;
  profile: UserProfile;
  recommendations: Recommendation[];
  contextProgramIds?: string[];
}): AgentAnswer {
  const intent = classifyConsultationIntent(input.message);
  const selected = selectProgram(
    input.message,
    input.recommendations,
    input.contextProgramIds ?? []
  );
  const handledBy: AgentId =
    intent === "policy"
      ? "policy-agent"
      : intent === "eligibility"
        ? "eligibility-agent"
        : intent === "announcement"
          ? "announcement-agent"
          : intent === "recommendation"
            ? "recommendation-agent"
            : "orchestrator";

  const draft =
    intent === "policy"
      ? policyAnswer(input.message)
      : intent === "eligibility"
        ? eligibilityAnswer(input.message, input.profile, selected)
        : intent === "announcement"
          ? announcementAnswer(input.message, selected)
          : intent === "recommendation"
            ? recommendationAnswer(input.recommendations, input.profile)
            : unsupportedAnswer();
  const checked = verifyAnswer(draft, intent, selected);

  return {
    answer: checked.answer,
    intent,
    handledBy,
    handledByLabel: AGENT_LABELS[handledBy],
    agentTrace: ["orchestrator", handledBy, "verification-agent"].filter(
      (agent, index, agents) => agents.indexOf(agent) === index
    ) as AgentId[],
    verification: checked.verification
  };
}
