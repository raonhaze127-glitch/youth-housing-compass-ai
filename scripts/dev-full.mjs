import { spawn } from "node:child_process";
import path from "node:path";

const root = process.cwd();
const apiDirectory = path.join(root, "services", "announcement-api");
const python = path.join(apiDirectory, ".venv", "Scripts", "python.exe");
const nextCli = path.join(root, "node_modules", "next", "dist", "bin", "next");

const api = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8001"],
  {
    cwd: apiDirectory,
    env: {
      ...process.env,
      ANNOUNCEMENT_SOURCE: process.env.ANNOUNCEMENT_SOURCE ?? "k_apt_alert",
      K_APT_ALERT_API_BASE_URL:
        process.env.K_APT_ALERT_API_BASE_URL ?? "https://k-apt-alert-proxy.onrender.com",
      SOURCE_TIMEOUT_SECONDS: process.env.SOURCE_TIMEOUT_SECONDS ?? "180"
    },
    stdio: "inherit",
    windowsHide: true
  }
);

const web = spawn(process.execPath, [nextCli, "dev"], {
  cwd: root,
  env: {
    ...process.env,
    ANNOUNCEMENT_API_BASE_URL:
      process.env.ANNOUNCEMENT_API_BASE_URL ?? "http://127.0.0.1:8001"
  },
  stdio: "inherit",
  windowsHide: true
});

let stopping = false;
function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  api.kill();
  web.kill();
  setTimeout(() => process.exit(exitCode), 250);
}

api.on("exit", (code) => {
  if (!stopping) stop(code ?? 1);
});
web.on("exit", (code) => {
  if (!stopping) stop(code ?? 1);
});
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
