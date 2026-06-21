import { NextResponse } from "next/server";
import { fetchAnnouncementApi, readJsonResponse } from "@/lib/announcement-api";

export async function GET(request: Request) {
  try {
    const query = new URL(request.url).searchParams.toString();
    const response = await fetchAnnouncementApi(`/v1/changes${query ? `?${query}` : ""}`);
    const { payload, status } = await readJsonResponse(response);
    return NextResponse.json(payload, { status });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "변동 이력 조회에 실패했습니다." },
      { status: 502 }
    );
  }
}
