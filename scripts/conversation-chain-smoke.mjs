const baseUrl = process.env.CHAT_BASE_URL ?? "https://youth-housing-compass-ai.vercel.app";

const scenarios = [
  {
    name: "경기도 가족 조건 추천 → 공고 해석 → 자격 후속",
    turns: [
      {
        message: "수원 40세 무주택 2세이하 1자녀",
        expect: {
          intent: "recommendation",
          handledBy: "recommendation-agent",
          profile: { region: "경기", district: "수원시" },
          answerIncludes: ["추천 근거", "수원시", "다음 확인이 필요합니다"],
          firstReasonIncludes: "수원시"
        }
      },
      {
        message: "1번 준비서류 알려줘",
        expect: {
          intent: "announcement",
          handledBy: "announcement-agent",
          answerIncludes: ["준비서류", "모집공고문 원문 기준"]
        }
      },
      {
        message: "1번 자격 가능해?",
        expect: {
          intent: "eligibility",
          handledBy: "eligibility-agent",
          answerIncludes: ["사전 자격 진단", "모집공고문 원문 기준"]
        }
      }
    ]
  },
  {
    name: "서울 청년 조건 추천 → 일정 → 원문",
    turns: [
      {
        message: "강남 28세 무주택 청년",
        expect: {
          intent: "recommendation",
          handledBy: "recommendation-agent",
          profile: { region: "서울", district: "강남구" },
          answerIncludes: ["서울 강남구", "추천 근거"]
        }
      },
      {
        message: "1번 신청기간 언제야?",
        expect: {
          intent: "announcement",
          handledBy: "announcement-agent",
          answerIncludes: ["신청기간", "모집공고문 원문 기준"]
        }
      },
      {
        message: "1번 원문 링크 줘",
        expect: {
          intent: "announcement",
          handledBy: "announcement-agent",
          answerIncludes: ["공식 원문"]
        }
      }
    ]
  },
  {
    name: "정책 설명 → 범위 밖 질문 안전 안내",
    turns: [
      {
        message: "행복주택과 국민임대 차이가 뭐야?",
        expect: {
          intent: "policy",
          handledBy: "policy-agent",
          showRecommendations: false,
          answerIncludes: ["30년", "최대 거주기간"]
        }
      },
      {
        message: "오늘 날씨 알려줘",
        expect: {
          intent: "unsupported",
          handledBy: "orchestrator",
          showRecommendations: false,
          answerIncludes: ["제가 잘 이해하지 못했어요", "아래 예시처럼 질문해 주세요"]
        }
      }
    ]
  },
  {
    name: "모호 지역명 안전 처리",
    turns: [
      {
        message: "광주시 40세 무주택 1자녀",
        expect: {
          intent: "recommendation",
          handledBy: "recommendation-agent",
          profile: { region: "경기", district: "광주시" },
          answerIncludes: ["경기 광주시", "광주시"]
        }
      },
      {
        message: "광주 40세 무주택 1자녀",
        resetContext: true,
        expect: {
          intent: "recommendation",
          handledBy: "recommendation-agent",
          profile: { region: "광주" },
          answerIncludes: ["광주"]
        }
      }
    ]
  }
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function includesAll(value, fragments, label) {
  for (const fragment of fragments ?? []) {
    assert(
      String(value ?? "").includes(fragment),
      `${label}에 "${fragment}"가 없습니다. 실제값: ${JSON.stringify(value)}`
    );
  }
}

async function ask(message, state) {
  const response = await fetch(`${baseUrl}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      profileContext: state.profile,
      contextProgramIds: state.contextProgramIds
    })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`${message} 요청 실패: ${JSON.stringify(payload)}`);
  }
  return payload;
}

const report = [];

for (const scenario of scenarios) {
  let state = { profile: undefined, contextProgramIds: [] };
  const turns = [];

  for (const [index, turn] of scenario.turns.entries()) {
    if (turn.resetContext) state = { profile: undefined, contextProgramIds: [] };

    const result = await ask(turn.message, state);
    const expected = turn.expect ?? {};

    assert(
      result.intent === expected.intent,
      `${scenario.name} ${index + 1}턴 intent 불일치: expected=${expected.intent}, actual=${result.intent}`
    );
    assert(
      result.handledBy === expected.handledBy,
      `${scenario.name} ${index + 1}턴 handledBy 불일치: expected=${expected.handledBy}, actual=${result.handledBy}`
    );

    if (expected.showRecommendations !== undefined) {
      assert(
        result.showRecommendations === expected.showRecommendations,
        `${scenario.name} ${index + 1}턴 showRecommendations 불일치: expected=${expected.showRecommendations}, actual=${result.showRecommendations}`
      );
    }

    for (const [key, value] of Object.entries(expected.profile ?? {})) {
      assert(
        result.profile?.[key] === value,
        `${scenario.name} ${index + 1}턴 profile.${key} 불일치: expected=${value}, actual=${result.profile?.[key]}`
      );
    }

    includesAll(result.answer, expected.answerIncludes, `${scenario.name} ${index + 1}턴 answer`);

    if (expected.firstReasonIncludes) {
      assert(
        result.recommendations?.[0]?.reasons?.some((reason) =>
          reason.includes(expected.firstReasonIncludes)
        ),
        `${scenario.name} ${index + 1}턴 1순위 추천 근거에 "${expected.firstReasonIncludes}"가 없습니다.`
      );
    }

    state = {
      profile: result.profile,
      contextProgramIds: result.recommendations?.map((item) => item.id) ?? []
    };

    turns.push({
      message: turn.message,
      intent: result.intent,
      handledBy: result.handledBy,
      recommendationCount: result.recommendations?.length ?? 0,
      firstId: result.recommendations?.[0]?.id,
      answerPreview: result.answer?.replace(/\s+/g, " ").slice(0, 180)
    });
  }

  report.push({ scenario: scenario.name, turns });
}

process.stdout.write(
  JSON.stringify(
    {
      baseUrl,
      scenarioCount: report.length,
      turnCount: report.reduce((sum, item) => sum + item.turns.length, 0),
      report
    },
    null,
    2
  ) + "\n"
);
