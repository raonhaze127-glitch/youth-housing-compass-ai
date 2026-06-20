import { NextResponse } from "next/server";
import { fetchAnnouncementApi, readJsonResponse } from "@/lib/announcement-api";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await context.params;
    const response = await fetchAnnouncementApi(
      `/v1/notices/${encodeURIComponent(id)}/raw`
    );
    const { payload, status } = await readJsonResponse(response);
    return NextResponse.json(payload, { status });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "공고 원문 분석에 실패했습니다." },
      { status: 502 }
    );
  }
}
