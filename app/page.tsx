"use client";

import { FormEvent, useMemo, useState } from "react";
import { ProgramCard } from "@/app/components/ProgramCard";
import { EligibilityPanel } from "@/app/components/EligibilityPanel";
import { ChangesPanel } from "@/app/components/ChangesPanel";
import type { Recommendation, UserProfile } from "@/lib/types";

type ApiResult = {
  profile: UserProfile;
  recommendations: Recommendation[];
  answer: string;
  dataSource: "sample" | "live";
  warning?: string;
};

type ConversationMessage = {
  role: "user" | "assistant";
  content: string;
};

const SAMPLE_PROMPTS = [
  "서울 사는 28세 무주택 직장인인데 월세 부담이 커요",
  "경기 거주 31세 무주택 청년이고 월소득 230만원이라 전세보증금 지원을 찾고 있어요",
  "서울 강서구 33세 신혼부부인데 공공임대주택을 알아보고 싶어요"
];

export default function Home() {
  const [message, setMessage] = useState(SAMPLE_PROMPTS[0]);
  const [result, setResult] = useState<ApiResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [conversation, setConversation] = useState<ConversationMessage[]>([]);

  const profileSummary = useMemo(() => {
    if (!result?.profile) return [];
    const profile = result.profile;
    return [
      profile.region ? `지역: ${profile.region}${profile.district ? ` ${profile.district}` : ""}` : "",
      profile.age ? `나이: 만 ${profile.age}세` : "",
      profile.homeless === true ? "무주택: 예" : profile.homeless === false ? "무주택: 아니오" : "",
      profile.incomeLevel === "low"
        ? "소득: 낮음"
        : profile.incomeLevel === "middle"
          ? "소득: 보통"
          : profile.incomeLevel === "high"
            ? "소득: 높음"
            : "",
      profile.householdType === "newlywed"
        ? "유형: 신혼부부"
        : profile.householdType === "youth"
          ? "유형: 청년"
          : "",
      profile.interests.length ? `관심: ${profile.interests.join(", ")}` : ""
    ].filter(Boolean);
  }, [result]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError("");

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          contextProgramIds: result?.recommendations.map((program) => program.id) ?? [],
          profileContext: result?.profile
        })
      });

      if (!response.ok) {
        const payload = (await response.json()) as { error?: string };
        throw new Error(payload.error ?? "추천 결과를 불러오지 못했습니다.");
      }

      const nextResult = (await response.json()) as ApiResult;
      setResult(nextResult);
      setConversation((current) => [
        ...current,
        { role: "user", content: message },
        { role: "assistant", content: nextResult.answer }
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="shell">
      <section className="workspace" aria-label="청년주거나침반 AI 추천 화면">
        <header className="topbar">
          <div>
            <p className="eyebrow">맞춤형 주거지원 안내</p>
            <h1>청년주거나침반 AI</h1>
          </div>
          <span className="status">
            {result?.dataSource === "live" ? "실공고 연동" : "규칙 기반 추천"}
          </span>
        </header>

        <section className="input-panel">
          <div className="prompt-copy">
            <h2>무엇을 찾고 계신가요?</h2>
            <p>현재 상황을 한 문장으로 입력하면 맞는 주거지원 사업을 골라드립니다.</p>
          </div>

          <form onSubmit={handleSubmit} className="search-form">
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              aria-label="주거 상황 입력"
              rows={3}
            />
            <div className="form-actions">
              <div className="prompt-buttons" aria-label="예시 입력">
                {SAMPLE_PROMPTS.map((prompt, index) => (
                  <button
                    key={prompt}
                    type="button"
                    title={prompt}
                    onClick={() => setMessage(prompt)}
                  >
                    예시 {index + 1}
                  </button>
                ))}
              </div>
              <button className="primary-button" type="submit" disabled={isLoading}>
                {isLoading ? "찾는 중" : "추천 받기"}
              </button>
            </div>
          </form>
          {error ? <p className="error">{error}</p> : null}
        </section>

        {conversation.length ? (
          <section className="conversation" aria-label="대화 내용" aria-live="polite">
            {conversation.map((item, index) => (
              <div className={`message ${item.role}`} key={`${item.role}-${index}`}>
                <span>{item.role === "user" ? "나" : "청나주"}</span>
                <p>{item.content}</p>
              </div>
            ))}
          </section>
        ) : null}

        {result ? (
          <section className="results">
            {result.warning ? <p className="data-warning">{result.warning}</p> : null}
            <div className="profile-box">
              <p className="section-label">추출된 조건</p>
              <div className="chips">
                {profileSummary.length ? (
                  profileSummary.map((item) => <span key={item}>{item}</span>)
                ) : (
                  <span>조건을 더 자세히 입력하면 추천 정확도가 올라갑니다.</span>
                )}
              </div>
            </div>

            {result.dataSource === "live" ? (
              <>
                <div className="feature-panels">
                  <EligibilityPanel />
                  <ChangesPanel />
                </div>
              </>
            ) : null}

            <div className="result-heading">
              <p className="section-label">추천 결과</p>
              <h2>조건에 맞는 주거지원 사업 {result.recommendations.length}개</h2>
            </div>

            <div className="cards">
              {result.recommendations.map((program, index) => (
                <ProgramCard program={program} index={index} key={program.id} />
              ))}
            </div>
          </section>
        ) : (
          <section className="empty-state">
            <p>예시 문장을 그대로 실행해도 추천 흐름을 확인할 수 있습니다.</p>
          </section>
        )}
      </section>
    </main>
  );
}
