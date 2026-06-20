import { NextResponse } from "next/server";
import { fetchAnnouncementApi } from "@/lib/announcement-api";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await context.params;
    const response = await fetchAnnouncementApi(
      `/v1/announcements/${encodeURIComponent(id)}/calendar.ics`
    );
    if (!response.ok) {
      return NextResponse.json(await response.json(), { status: response.status });
    }
    return new Response(await response.arrayBuffer(), {
      headers: {
        "Content-Type": "text/calendar; charset=utf-8",
        "Content-Disposition": `attachment; filename="${encodeURIComponent(id)}.ics"`
      }
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "일정 파일 생성에 실패했습니다." },
      { status: 502 }
    );
  }
}
