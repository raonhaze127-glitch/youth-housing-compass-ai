export function getAnnouncementApiBaseUrl() {
  return process.env.ANNOUNCEMENT_API_BASE_URL?.trim().replace(/\/$/, "") ?? "";
}

export async function fetchAnnouncementApi(
  path: string,
  init?: RequestInit
): Promise<Response> {
  const baseUrl = getAnnouncementApiBaseUrl();
  if (!baseUrl) {
    throw new Error("공고 서비스가 연결되지 않았습니다.");
  }

  return fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    signal: init?.signal ?? AbortSignal.timeout(12_000)
  });
}

export async function readJsonResponse(response: Response) {
  const payload = await response.json();
  return { payload, status: response.status };
}
