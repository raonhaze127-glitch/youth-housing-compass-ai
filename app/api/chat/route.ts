import { NextResponse } from "next/server";
import { parseUserInput } from "@/lib/parser";
import { loadHousingPrograms } from "@/lib/programs";
import { recommendPrograms } from "@/lib/recommender";
import { answerWithAgents } from "@/lib/agents";
import { applyLiveMatches } from "@/lib/live-match";
import type { UserProfile } from "@/lib/types";

export async function POST(request: Request) {
  const body = (await request.json()) as {
    message?: string;
    contextProgramIds?: string[];
    profileContext?: UserProfile;
  };
  const message = body.message?.trim();

  if (!message) {
    return NextResponse.json(
      { error: "상황을 한 문장으로 입력해주세요." },
      { status: 400 }
    );
  }

  const parsedProfile = parseUserInput(message);
  const previous = body.profileContext;
  const profile: UserProfile = previous
    ? {
        region: parsedProfile.region ?? previous.region,
        district: parsedProfile.district ?? previous.district,
        age: parsedProfile.age ?? previous.age,
        homeless: parsedProfile.homeless ?? previous.homeless,
        incomeLevel: parsedProfile.incomeLevel !== "unknown" ? parsedProfile.incomeLevel : previous.incomeLevel,
        householdType: parsedProfile.householdType !== "unknown" ? parsedProfile.householdType : previous.householdType,
        children: parsedProfile.children ?? previous.children,
        childrenCount: parsedProfile.childrenCount ?? previous.childrenCount,
        youngestChildAgeMax: parsedProfile.youngestChildAgeMax ?? previous.youngestChildAgeMax,
        interests: parsedProfile.interests.length ? parsedProfile.interests : previous.interests,
        rawText: message
      }
    : parsedProfile;

  try {
    const loaded = await loadHousingPrograms();
    const programs = loaded.programs;
    let recommendations = recommendPrograms(profile, programs);
    if (loaded.dataSource === "live") {
      recommendations = await applyLiveMatches(profile, recommendations);
    }
    const consultation = answerWithAgents({
      message,
      profile,
      recommendations,
      contextProgramIds: body.contextProgramIds ?? []
    });

    return NextResponse.json({
      profile,
      recommendations,
      ...consultation,
      dataSource: loaded.dataSource,
      warning: loaded.warning
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "공고 데이터를 불러오지 못했습니다."
      },
      { status: 502 }
    );
  }
}
