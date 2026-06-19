import { NextResponse } from "next/server";
import programs from "@/data/housing_programs.json";
import { parseUserInput } from "@/lib/parser";
import { recommendPrograms } from "@/lib/recommender";
import type { HousingProgram } from "@/lib/types";

export async function POST(request: Request) {
  const body = (await request.json()) as { message?: string };
  const message = body.message?.trim();

  if (!message) {
    return NextResponse.json(
      { error: "상황을 한 문장으로 입력해주세요." },
      { status: 400 }
    );
  }

  const profile = parseUserInput(message);
  const recommendations = recommendPrograms(profile, programs as HousingProgram[]);

  return NextResponse.json({
    profile,
    recommendations
  });
}
