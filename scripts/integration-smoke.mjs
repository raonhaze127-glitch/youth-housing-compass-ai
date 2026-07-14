import { spawn } from "node:child_process";
import { once } from "node:events";
import path from "node:path";

const root = process.cwd();
const apiDirectory = path.join(root, "services", "announcement-api");
const python = path.join(apiDirectory, ".venv", "Scripts", "python.exe");
const nextCli = path.join(root, "node_modules", "next", "dist", "bin", "next");

const processes = [];

function start(command, args, options) {
  const child = spawn(command, args, {
    ...options,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true
  });
  processes.push(child);
  return child;
}

async function waitFor(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch {
      // 서버가 준비될 때까지 짧게 재시도합니다.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${url} 준비 시간을 초과했습니다.`);
}

async function stop(child) {
  if (child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    once(child, "exit"),
    new Promise((resolve) => setTimeout(resolve, 3_000))
  ]);
}

const api = start(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"],
  { cwd: apiDirectory }
);
const web = start(
  process.execPath,
  [nextCli, "start", "-p", "3010"],
  {
    cwd: root,
    env: {
      ...process.env,
      ANNOUNCEMENT_API_BASE_URL: "http://127.0.0.1:8010"
    }
  }
);

try {
  const healthResponse = await waitFor("http://127.0.0.1:8010/health");
  const health = await healthResponse.json();
  await waitFor("http://127.0.0.1:3010");

  const response = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "서울 사는 28세 무주택 청년이고 월세 지원을 찾고 있어요"
    })
  });
  const result = await response.json();

  if (!response.ok) throw new Error(JSON.stringify(result));
  if (!result.recommendations?.length) throw new Error("추천 결과가 비어 있습니다.");
  if (result.dataSource !== "snapshot") {
    throw new Error("검증된 실공고 스냅샷을 사용하지 않았습니다.");
  }
  if (!["LH", "SH", "GH", "청약홈"].includes(result.recommendations[0].organization)) {
    throw new Error("공공주택 범위 밖의 추천 결과가 포함됐습니다.");
  }
  if (
    result.handledBy !== "recommendation-agent" ||
    result.agentTrace?.at(-1) !== "verification-agent"
  ) {
    throw new Error("추천 질문이 추천·검증 Agent 흐름을 거치지 않았습니다.");
  }

  const followUpResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "1번 준비서류 알려줘",
      profileContext: result.profile,
      contextProgramIds: result.recommendations.map((item) => item.id)
    })
  });
  const followUp = await followUpResponse.json();
  if (!followUpResponse.ok || !followUp.answer?.includes("준비서류")) {
    throw new Error("후속 질문이 이전 추천 맥락을 사용하지 못했습니다.");
  }
  if (followUp.handledBy !== "announcement-agent") {
    throw new Error("공고 준비서류 질문이 공고 해석 Agent로 전달되지 않았습니다.");
  }

  const eligibilityResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "1번 자격 가능해?",
      profileContext: result.profile,
      contextProgramIds: result.recommendations.map((item) => item.id)
    })
  });
  const eligibility = await eligibilityResponse.json();
  if (
    !eligibilityResponse.ok ||
    eligibility.handledBy !== "eligibility-agent" ||
    !eligibility.answer?.includes("모집공고문 원문 기준") ||
    eligibility.answer.length > 700
  ) {
    throw new Error("자격 질문의 담당 Agent 또는 검증 안내가 올바르지 않습니다.");
  }

  const policyResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "공공임대와 공공분양의 차이가 뭐야?" })
  });
  const policy = await policyResponse.json();
  if (
    !policyResponse.ok ||
    policy.handledBy !== "policy-agent" ||
    !policy.answer?.includes("소유권") ||
    !policy.answer?.includes("참고 출처") ||
    policy.showRecommendations !== false
  ) {
    throw new Error("정책 설명 질문이 Policy Agent로 전달되지 않았습니다.");
  }

  const housingTypePolicyResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "장기전세는?" })
  });
  const housingTypePolicy = await housingTypePolicyResponse.json();
  if (
    !housingTypePolicyResponse.ok ||
    housingTypePolicy.handledBy !== "policy-agent" ||
    housingTypePolicy.intent !== "policy"
  ) {
    throw new Error("주택 유형 단독 질문이 Policy Agent로 고정되지 않았습니다.");
  }

  const integratedRentalPolicyResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "통합공공임대는?" })
  });
  const integratedRentalPolicy = await integratedRentalPolicyResponse.json();
  if (
    !integratedRentalPolicyResponse.ok ||
    integratedRentalPolicy.handledBy !== "policy-agent" ||
    !integratedRentalPolicy.answer?.includes("우선공급") ||
    !integratedRentalPolicy.answer?.includes("일반공급")
  ) {
    throw new Error("통합공공임대 가이드 답변이 Policy Agent에 반영되지 않았습니다.");
  }

  const typePolicyCases = [
    { message: "국민임대는?", expected: "30년" },
    { message: "행복주택은?", expected: "최대 거주기간" },
    { message: "공공임대는?", expected: "분양전환" },
    { message: "영구임대는?", expected: "기초생활수급자" },
    { message: "장기전세는?", expected: "보증금" },
    { message: "매입임대는?", expected: "기존 주택을 매입" },
    { message: "전세임대는?", expected: "전세계약" },
    { message: "주거지원사업은?", expected: "주거위기" }
  ];
  for (const typePolicyCase of typePolicyCases) {
    const typePolicyResponse = await fetch("http://127.0.0.1:3010/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: typePolicyCase.message })
    });
    const typePolicy = await typePolicyResponse.json();
    if (
      !typePolicyResponse.ok ||
      typePolicy.handledBy !== "policy-agent" ||
      typePolicy.intent !== "policy" ||
      !typePolicy.answer?.includes(typePolicyCase.expected)
    ) {
      throw new Error(`${typePolicyCase.message} 유형별 정책 답변이 올바르지 않습니다.`);
    }
  }

  const comparisonPolicyCases = [
    { message: "행복주택과 국민임대 차이가 뭐야?", expected: ["30년", "최대 거주기간"] },
    { message: "매입임대와 전세임대 차이 알려줘", expected: ["기존 주택을 매입", "전세계약"] },
    { message: "장기전세와 전세임대 차이는?", expected: ["장기 거주", "집을 찾"] },
    { message: "통합공공임대와 국민임대 차이는?", expected: ["하나의 틀로 통합", "모집공고"] }
  ];
  for (const comparison of comparisonPolicyCases) {
    const comparisonResponse = await fetch("http://127.0.0.1:3010/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: comparison.message })
    });
    const comparisonResult = await comparisonResponse.json();
    if (
      !comparisonResponse.ok ||
      comparisonResult.handledBy !== "policy-agent" ||
      comparisonResult.showRecommendations !== false ||
      comparison.expected.some((text) => !comparisonResult.answer?.includes(text))
    ) {
      throw new Error(`${comparison.message} 비교 답변이 올바르지 않습니다.`);
    }
  }

  const unsupportedResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "오늘 날씨 알려줘" })
  });
  const unsupported = await unsupportedResponse.json();
  if (
    !unsupportedResponse.ok ||
    unsupported.intent !== "unsupported" ||
    unsupported.showRecommendations !== false ||
    !unsupported.answer?.includes("제가 잘 이해하지 못했어요") ||
    !unsupported.answer?.includes("행복주택과 국민임대의 차이가 뭐야?")
  ) {
    throw new Error("상담 범위 밖 질문의 경계 응답이 올바르지 않습니다.");
  }


  const generalEligibilityResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "만 29세 무주택 청년인데 신청할 수 있어?" })
  });
  const generalEligibility = await generalEligibilityResponse.json();
  if (
    !generalEligibilityResponse.ok ||
    generalEligibility.handledBy !== "eligibility-agent" ||
    generalEligibility.showRecommendations !== false
  ) {
    throw new Error("특정 공고가 없는 일반 자격 질문에서 추천 카드가 숨겨지지 않았습니다.");
  }

  const familyResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "고양시 40세 무주택 2세이하 1자녀"
    })
  });
  const familyResult = await familyResponse.json();
  if (!familyResponse.ok) throw new Error(JSON.stringify(familyResult));
  if (
    familyResult.profile?.region !== "경기" ||
    familyResult.profile?.district !== "고양시" ||
    familyResult.profile?.childrenCount !== 1 ||
    familyResult.profile?.youngestChildAgeMax !== 2
  ) {
    throw new Error("시·군 또는 자녀 조건을 정확히 추출하지 못했습니다.");
  }
  if (
    familyResult.recommendations.some(
      (item) =>
        !["경기", "전국"].includes(item.region) ||
        /청년형|도전숙|공공기숙사|자립준비청년/.test(item.title)
    )
  ) {
    throw new Error("지역·연령·전용대상과 명백히 맞지 않는 공고가 포함됐습니다.");
  }
  if (
    familyResult.recommendations.some(
      (item) =>
        !item.title.includes("고양") &&
        !item.reasons?.some((reason) => reason.includes("고양시"))
    )
  ) {
    throw new Error("고양시 근거가 확인된 공고 외의 지역 후보가 함께 노출됐습니다.");
  }
  const goyangProgram = familyResult.recommendations.find(
    (item) => item.title.includes("고양") || item.reasons?.some((reason) => reason.includes("고양시"))
  );
  if (!goyangProgram) {
    throw new Error("고양시 공급지역 근거가 있는 후보를 추천하지 못했습니다.");
  }

  const shortDistrictResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "수원 40세 무주택 2세이하 1자녀"
    })
  });
  const shortDistrictResult = await shortDistrictResponse.json();
  if (
    !shortDistrictResponse.ok ||
    shortDistrictResult.profile?.region !== "경기" ||
    shortDistrictResult.profile?.district !== "수원시"
  ) {
    throw new Error("경기도 시 이름을 줄여 입력한 경우 표준 시 단위로 해석하지 못했습니다.");
  }


  const gwangjuDistrictResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "광주시 40세 무주택 1자녀" })
  });
  const gwangjuDistrictResult = await gwangjuDistrictResponse.json();
  if (
    !gwangjuDistrictResponse.ok ||
    gwangjuDistrictResult.profile?.region !== "경기" ||
    gwangjuDistrictResult.profile?.district !== "광주시" ||
    gwangjuDistrictResult.recommendations.some(
      (item) => !item.reasons?.some((reason) => /광주시|전국 단위/.test(reason))
    )
  ) {
    throw new Error("경기 광주시와 무관한 지역 공고가 추천에 포함됐습니다.");
  }

  const seoulDistrictResponse = await fetch("http://127.0.0.1:3010/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "강남 28세 무주택 청년"
    })
  });
  const seoulDistrictResult = await seoulDistrictResponse.json();
  if (
    !seoulDistrictResponse.ok ||
    seoulDistrictResult.profile?.region !== "서울" ||
    seoulDistrictResult.profile?.district !== "강남구"
  ) {
    throw new Error("서울 구 이름을 줄여 입력한 경우 표준 구 단위로 해석하지 못했습니다.");
  }

  const exampleCases = [
    {
      message: "서울 사는 28세 무주택 직장인인데 월세 부담이 커요",
      validate: (value) => value.recommendations.every(
        (item) =>
          (item.region === "서울" || /전국|전\s*지역/.test(item.title)) &&
          !/창업인의\s*집|연극인(?:두레)?주택/.test(item.title)
      )
    },
    {
      message: "경기 거주 31세 무주택 청년이고 월소득 230만원이라 전세보증금 지원을 찾고 있어요",
      allowEmpty: true,
      validate: (value) => value.recommendations.every(
        (item) =>
          !/신혼|신생아/.test(item.title) &&
          /전세임대|전세지원|전세형|든든전세|보증금\s*(?:지원|대출|보증료)/.test(
            `${item.title} ${item.housing_type} ${item.summary}`
          )
      )
    },
    {
      message: "서울 강서구 33세 신혼부부인데 공공임대주택을 알아보고 싶어요",
      allowEmpty: true,
      validate: (value) => value.recommendations.every(
        (item) =>
          !/기숙사형|청년\s*매입/.test(item.title) &&
          (item.region === "서울" || /전국|전\s*지역/.test(item.title))
      )
    }
  ];
  for (const exampleCase of exampleCases) {
    const exampleResponse = await fetch("http://127.0.0.1:3010/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: exampleCase.message })
    });
    const exampleResult = await exampleResponse.json();
    if (
      !exampleResponse.ok ||
      exampleResult.handledBy !== "recommendation-agent" ||
      (!exampleCase.allowEmpty && !exampleResult.recommendations.length) ||
      exampleResult.recommendations.length > 6 ||
      !exampleCase.validate(exampleResult)
    ) {
      throw new Error(
        `${exampleCase.message} 예시 질문의 분류 또는 추천 필터가 올바르지 않습니다: ${JSON.stringify({
          handledBy: exampleResult.handledBy,
          recommendations: exampleResult.recommendations?.map((item) => ({
            title: item.title,
            region: item.region,
            target: item.target
          }))
        })}`
      );
    }
  }

  process.stdout.write(
    JSON.stringify(
      {
        api_source: health.source,
        data_source: result.dataSource,
        profile_region: result.profile.region,
        recommendation_count: result.recommendations.length,
        first_id: result.recommendations[0].id,
        first_status: result.recommendations[0].status,
        family_recommendation_count: familyResult.recommendations.length,
        family_first_id: familyResult.recommendations[0]?.id,
        short_district: shortDistrictResult.profile?.district,
        seoul_district: seoulDistrictResult.profile?.district,
        follow_up: followUp.answer,
        agents: {
          recommendation: result.handledBy,
          announcement: followUp.handledBy,
          eligibility: eligibility.handledBy,
          policy: policy.handledBy,
          unsupported: unsupported.handledBy
        }
      },
      null,
      2
    ) + "\n"
  );
} catch (error) {
  const apiError = await new Promise((resolve) => {
    let output = "";
    api.stderr.on("data", (chunk) => (output += chunk));
    setTimeout(() => resolve(output), 100);
  });
  const webError = await new Promise((resolve) => {
    let output = "";
    web.stderr.on("data", (chunk) => (output += chunk));
    setTimeout(() => resolve(output), 100);
  });
  throw new Error(`${error.message}\nAPI: ${apiError}\nWEB: ${webError}`);
} finally {
  await Promise.all(processes.map(stop));
}
