import { spawn } from "node:child_process";
import { once } from "node:events";
import path from "node:path";

const root = process.cwd();
const apiDirectory = path.join(root, "services", "announcement-api");
const python = path.join(apiDirectory, ".venv", "Scripts", "python.exe");
const nextCli = path.join(root, "node_modules", "next", "dist", "bin", "next");
const children = [];

function start(command, args, options) {
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  children.push(child);
  return child;
}

async function waitFor(url, timeoutMs = 40_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new Error(`${url} 준비 시간을 초과했습니다.`);
}

async function jsonRequest(url, init, timeoutMs = 210_000) {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${url}: ${response.status} ${JSON.stringify(payload).slice(0, 500)}`);
  return payload;
}

async function stop(child) {
  if (child.exitCode !== null) return;
  child.kill();
  await Promise.race([once(child, "exit"), new Promise((resolve) => setTimeout(resolve, 3000))]);
}

start(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8011"], {
  cwd: apiDirectory,
  env: {
    ...process.env,
    ANNOUNCEMENT_SOURCE: "direct",
    DATA_GO_KR_API_KEY: process.env.DATA_GO_KR_API_KEY ?? "",
    SOURCE_TIMEOUT_SECONDS: "180"
  }
});
start(process.execPath, [nextCli, "start", "-p", "3011"], {
  cwd: root,
  env: { ...process.env, ANNOUNCEMENT_API_BASE_URL: "http://127.0.0.1:8011" }
});

try {
  await waitFor("http://127.0.0.1:8011/health");
  await waitFor("http://127.0.0.1:3011");

  const chat = await jsonRequest("http://127.0.0.1:3011/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "서울 경기 무주택 28세 청년 공고 알려줘" })
  });
  if (chat.dataSource !== "live" || !chat.recommendations?.length) {
    throw new Error("실공고 추천 결과가 생성되지 않았습니다.");
  }

  const score = await jsonRequest("http://127.0.0.1:3011/api/eligibility/score", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      profile: {
        no_house_years: 3,
        dependents: 0,
        no_house: true,
        ever_owned_house: false,
        subscription_account: { years: 3, deposit_count: 18 }
      }
    })
  });

  const changes = await jsonRequest("http://127.0.0.1:3011/api/changes?limit=2");
  const match = await jsonRequest("http://127.0.0.1:3011/api/announcements/match", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      profile: { preferred_categories: ["APT"], preferred_regions: ["서울"], min_units: 100 },
      announcements: [{ id: "apt_test", house_category: "APT", region: "서울", total_units: "500" }]
    })
  });
  const candidate = chat.recommendations.find((item) => item.source_id);
  const competitionCandidate = chat.recommendations.find((item) => /^(apt|ppr|rem)_/.test(item.source_id ?? ""));
  const optional = {};
  if (competitionCandidate) {
    const id = encodeURIComponent(competitionCandidate.source_id);
    try {
      const competition = await jsonRequest(`http://127.0.0.1:3011/api/announcements/${id}/competition`);
      optional.competition_source = competition.source ?? competition.result?.source ?? "returned";
    } catch (error) {
      optional.competition_error = error.message;
    }
  }
  if (candidate) {
    const id = encodeURIComponent(candidate.source_id);
    try {
      const calendar = await fetch(`http://127.0.0.1:3011/api/announcements/${id}/calendar`, {
        signal: AbortSignal.timeout(60_000)
      });
      optional.calendar_status = calendar.status;
      optional.calendar_type = calendar.headers.get("content-type");
    } catch (error) {
      optional.calendar_error = error.message;
    }
    try {
      const raw = await jsonRequest(`http://127.0.0.1:3011/api/announcements/${id}/raw`, undefined, 180_000);
      optional.raw_chars = raw.char_count ?? raw.text?.length ?? 0;
    } catch (error) {
      optional.raw_error = error.message;
    }
  }

  process.stdout.write(JSON.stringify({
    live_count: chat.recommendations.length,
    first_source: chat.recommendations[0].source_type,
    score_total: score.scores?.total,
    changes_status: changes.tracking_status ?? changes.status,
    changes_count: changes.count ?? changes.changes?.length ?? 0,
    match_level: match.matches?.[0]?.fit_level,
    source_prefixes: [...new Set(chat.recommendations.map((item) => item.source_id?.split("_")[0]).filter(Boolean))],
    ...optional
  }, null, 2) + "\n");
} finally {
  await Promise.all(children.map(stop));
}
