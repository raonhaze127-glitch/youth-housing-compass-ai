import { NextResponse } from "next/server";
import { fetchAnnouncementApi, readJsonResponse } from "@/lib/announcement-api";

async function forward(method: "PUT" | "DELETE", request: Request, userId: string, announcementId: string) {
  const body = method === "PUT" ? JSON.stringify(await request.json()) : undefined;
  const response = await fetchAnnouncementApi(
    `/v1/users/${encodeURIComponent(userId)}/favorites/${encodeURIComponent(announcementId)}`,
    { method, headers: body ? { "Content-Type": "application/json" } : undefined, body }
  );
  const { payload, status } = await readJsonResponse(response);
  return NextResponse.json(payload, { status });
}

export async function PUT(request: Request, context: { params: Promise<{ userId: string; announcementId: string }> }) {
  try { const params = await context.params; return await forward("PUT", request, params.userId, params.announcementId); }
  catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "관심 공고 저장 실패" }, { status: 502 }); }
}

export async function DELETE(request: Request, context: { params: Promise<{ userId: string; announcementId: string }> }) {
  try { const params = await context.params; return await forward("DELETE", request, params.userId, params.announcementId); }
  catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "관심 공고 삭제 실패" }, { status: 502 }); }
}
