import { NextResponse } from "next/server";
import { fetchAnnouncementApi, readJsonResponse } from "@/lib/announcement-api";

export async function GET(_request: Request, context: { params: Promise<{ userId: string }> }) {
  try {
    const { userId } = await context.params;
    const response = await fetchAnnouncementApi(`/v1/users/${encodeURIComponent(userId)}/favorites`);
    const { payload, status } = await readJsonResponse(response);
    return NextResponse.json(payload, { status });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "관심 공고 조회 실패" }, { status: 502 });
  }
}
