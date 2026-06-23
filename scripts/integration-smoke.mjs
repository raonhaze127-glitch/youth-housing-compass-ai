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
  if (!["LH", "SH", "GH"].includes(result.recommendations[0].organization)) {
    throw new Error("공공주택 범위 밖의 추천 결과가 포함됐습니다.");
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
  if (familyResult.recommendations.length !== 1) {
    throw new Error("고양시 근거가 확인된 공고 외의 지역 후보가 함께 노출됐습니다.");
  }
  const goyangProgram = familyResult.recommendations.find(
    (item) => item.source_id === "gh_64932"
  );
  if (!goyangProgram?.reasons?.some((reason) => reason.includes("고양시"))) {
    throw new Error("공고문 안의 고양시 공급지역을 추천 근거로 사용하지 못했습니다.");
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
        follow_up: followUp.answer
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
