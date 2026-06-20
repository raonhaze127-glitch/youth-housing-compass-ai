import { NextResponse } from "next/server";
import { fetchAnnouncementApi, readJsonResponse } from "@/lib/announcement-api";

async function forward(method: string, request: Request, userId: string) {
  const body = method === "PUT" ? JSON.stringify(await request.json()) : undefined;
  const response = await fetchAnnouncementApi(
    `/v1/users/${encodeURIComponent(userId)}/profile`,
    { method, headers: body ? { "Content-Type": "application/json" } : undefined, body }
  );
  const { payload, status } = await readJsonResponse(response);
  return NextResponse.json(payload, { status });
}

export async function GET(request: Request, context: { params: Promise<{ userId: string }> }) {
  try { return await forward("GET", request, (await context.params).userId); }
  catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "프로필 조회 실패" }, { status: 502 }); }
}

export async function PUT(request: Request, context: { params: Promise<{ userId: string }> }) {
  try { return await forward("PUT", request, (await context.params).userId); }
  catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "프로필 저장 실패" }, { status: 502 }); }
}

export async function DELETE(request: Request, context: { params: Promise<{ userId: string }> }) {
  try { return await forward("DELETE", request, (await context.params).userId); }
  catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "프로필 삭제 실패" }, { status: 502 }); }
}
