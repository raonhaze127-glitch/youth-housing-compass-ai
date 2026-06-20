import { NextResponse } from "next/server";
import { fetchAnnouncementApi, readJsonResponse } from "@/lib/announcement-api";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const response = await fetchAnnouncementApi("/v1/announcements/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const { payload, status } = await readJsonResponse(response);
    return NextResponse.json(payload, { status });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "공고 매칭에 실패했습니다." },
      { status: 502 }
    );
  }
}
