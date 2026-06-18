"use client";

import { FormEvent, useMemo, useState } from "react";
import type { Recommendation, UserProfile } from "@/lib/types";

type ApiResult = {
  profile: UserProfile;
  recommendations: Recommendation[];
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
      const response = await fetch("/api/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message })
      });

      if (!response.ok) {
        const payload = (await response.json()) as { error?: string };
        throw new Error(payload.error ?? "추천 결과를 불러오지 못했습니다.");
      }

      setResult((await response.json()) as ApiResult);
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
          <span className="status">규칙 기반 추천</span>
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
                {SAMPLE_PROMPTS.map((prompt) => (
                  <button key={prompt} type="button" onClick={() => setMessage(prompt)}>
                    예시
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

        {result ? (
          <section className="results">
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

            <div className="result-heading">
              <p className="section-label">추천 결과</p>
              <h2>신청 가능성이 높은 사업 3개</h2>
            </div>

            <div className="cards">
              {result.recommendations.map((program, index) => (
                <article className="program-card" key={program.id}>
                  <div className="card-head">
                    <span className="rank">{index + 1}</span>
                    <div>
                      <p>{program.organization}</p>
                      <h3>{program.title}</h3>
                    </div>
                  </div>
                  <p className="summary">{program.summary}</p>
                  <dl>
                    <div>
                      <dt>추천 이유</dt>
                      <dd>{program.reasons.slice(0, 2).join(" ")}</dd>
                    </div>
                    <div>
                      <dt>신청기간</dt>
                      <dd>
                        {program.apply_start} ~ {program.apply_end}
                      </dd>
                    </div>
                    <div>
                      <dt>지원내용</dt>
                      <dd>{program.benefit_summary}</dd>
                    </div>
                  </dl>
                  <a href={program.url} target="_blank" rel="noreferrer">
                    원문 확인
                  </a>
                </article>
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
