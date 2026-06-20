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
  if (result.recommendations[0].source_type !== "sample") {
    throw new Error("공고 서비스의 샘플 소스를 거치지 않았습니다.");
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

  process.stdout.write(
    JSON.stringify(
      {
        api_source: health.source,
        profile_region: result.profile.region,
        recommendation_count: result.recommendations.length,
        first_id: result.recommendations[0].id,
        first_status: result.recommendations[0].status,
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
