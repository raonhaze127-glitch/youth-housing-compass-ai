"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { ProgramCard } from "@/app/components/ProgramCard";
import { EligibilityPanel } from "@/app/components/EligibilityPanel";
import { ChangesPanel } from "@/app/components/ChangesPanel";
import type { Recommendation, UserProfile } from "@/lib/types";

type ApiResult = {
  profile: UserProfile;
  recommendations: Recommendation[];
  answer: string;
  handledBy: string;
  handledByLabel: string;
  dataSource: "sample" | "snapshot" | "live";
  warning?: string;
};

type ConversationMessage = {
  role: "user" | "assistant";
  content: string;
  label?: string;
};

type ChatResponse = Partial<ApiResult> & { error?: string };

async function readChatResponse(response: Response): Promise<ChatResponse> {
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();

  if (!contentType.includes("application/json")) {
    throw new Error(
      "추천 서버가 갱신 중입니다. 잠시 후 다시 시도해주세요."
    );
  }

  try {
    return JSON.parse(body) as ChatResponse;
  } catch {
    throw new Error("추천 서버 응답을 읽지 못했습니다. 잠시 후 다시 시도해주세요.");
  }
}

const SAMPLE_PROMPTS = [
  "서울 사는 28세 무주택 직장인인데 월세 부담이 커요",
  "경기 거주 31세 무주택 청년이고 월소득 230만원이라 전세보증금 지원을 찾고 있어요",
  "서울 강서구 33세 신혼부부인데 공공임대주택을 알아보고 싶어요"
];

// 공고 변경 추적과 청약 가점 계산은 검증이 끝날 때까지 화면에서 숨깁니다.
const ENABLE_DECISION_TOOLS =
  process.env.NEXT_PUBLIC_ENABLE_DECISION_TOOLS === "true";

const STATUS_ORDER = {
  open: 0,
  planned: 1,
  unknown: 2,
  closed: 3
} as const;

// 로고 3번: 아늑한 집 & 부드러운 길잡이 (SVG)
function CompassLogo({ className = "w-12 h-12", style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg
      className={className}
      style={style}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* 아늑한 집 모양 지붕 */}
      <path
        d="M16 28L32 14L48 28"
        stroke="currentColor"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M22 28V42C22 43.1046 22.8954 44 24 44H40C41.1046 44 42 43.1046 42 42V28"
        stroke="currentColor"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* 집 내부의 미니멀 나침반 방향선 */}
      <circle
        cx="32"
        cy="31"
        r="5"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeDasharray="2 2"
      />
      {/* 길을 안내하는 대각선 화살표 침 */}
      <path
        d="M30 33L34 29"
        stroke="currentColor"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      <path
        d="M34 29H31M34 29V32"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* 로고 하단의 아늑하고 부드럽게 감싸안는 곡선 길잡이 라인 */}
      <path
        d="M10 44C10 44 21 52 32 52C43 52 54 44 54 44"
        stroke="currentColor"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function Home() {
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<ApiResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [conversation, setConversation] = useState<ConversationMessage[]>([]);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // message 값이 바뀔 때마다 textarea의 높이를 scrollHeight에 맞추어 자동 조절 (렌더링 타이밍 보장)
  useEffect(() => {
    const adjustHeight = () => {
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
        textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
      }
    };

    adjustHeight();

    // 마운트 시점 및 폰트 렌더링 지연에 따른 실측 오차를 방지하기 위해 80ms 후 추가 실행
    const timer = setTimeout(adjustHeight, 80);
    return () => clearTimeout(timer);
  }, [message]);

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
      profile.childrenCount || profile.children?.length
        ? `자녀: ${profile.childrenCount ?? profile.children?.length}명${profile.youngestChildAgeMax !== undefined ? ` (${profile.youngestChildAgeMax}세 이하)` : profile.children?.[0]?.age ? ` (${profile.children[0].age}세)` : ""}`
        : "",
      profile.interests.length ? `관심: ${profile.interests.join(", ")}` : ""
    ].filter(Boolean);
  }, [result]);

  const sortedRecommendations = useMemo(() => {
    return [...(result?.recommendations ?? [])].sort(
      (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || b.score - a.score
    );
  }, [result?.recommendations]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!message.trim()) return;

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

      const payload = await readChatResponse(response);

      if (!response.ok) {
        throw new Error(payload.error ?? "추천 결과를 불러오지 못했습니다.");
      }

      const nextResult = payload as ApiResult;
      setResult(nextResult);
      setConversation((current) => [
        ...current,
        { role: "user", content: message },
        {
          role: "assistant",
          content: nextResult.answer,
          label: nextResult.handledByLabel
        }
      ]);
      setMessage(""); // 전송 후 입력 창 비우기 (ChatGPT 스타일)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
    } finally {
      setIsLoading(false);
    }
  }

  const isChatActive = conversation.length > 0;

  return (
    <main className="shell">
      <section className="workspace" aria-label="청년주거나침반 AI 추천 화면">

        {/* 상단바: 대화가 시작된 후에만 헤더를 노출하여 몰입감을 높임 */}
        {isChatActive && (
          <header className="topbar">
            <div className="topbar-branding">
              <CompassLogo style={{ width: 24, height: 24 }} />
              <h1>청년주거나침반 AI</h1>
            </div>
            <span className="status">
              {result?.dataSource === "live"
                ? "실시간 실공고"
                : result?.dataSource === "snapshot"
                  ? "저장 실공고"
                  : "규칙 기반 추천"}
            </span>
          </header>
        )}

        {/* 대화 전 웰컴 스크린 */}
        {!isChatActive && (
          <section className="chat-welcome">
            <div className="logo-wrapper" style={{ display: "flex", alignItems: "center", gap: "10px", color: "var(--accent)", marginBottom: "20px" }}>
              <CompassLogo style={{ width: 38, height: 38 }} />
              <span style={{ fontSize: "26px", fontWeight: 850, letterSpacing: "-0.03em", color: "var(--accent)" }}>
                청년주거나침반
              </span>
            </div>
            <h1>안녕하세요, 어떤 집을 찾으시나요?</h1>
            <p>
              조건이나 고민을 대화하듯이 입력하시면 맞춤형 공공주택을 골라 나침반처럼 길을 안내해 드립니다.
            </p>
          </section>
        )}

        {/* 대화 피드 영역 */}
        {isChatActive && (
          <section className="conversation" aria-label="대화 내용" aria-live="polite">
            {conversation.map((item, index) => (
              <div className={`message ${item.role}`} key={`${item.role}-${index}`}>
                <span>{item.role === "user" ? "나" : item.label ?? "청나주"}</span>
                <p>{item.content}</p>
              </div>
            ))}
          </section>
        )}

        {/* 결과 분석 및 추천 리스트 출력 영역 */}
        {result && isChatActive && (
          <section className="results">
            {result.warning ? <p className="data-warning">{result.warning}</p> : null}

            {/* 조건 요약 박스 */}
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

            {/* 실공고 연동 기능 패널들 */}
            {result.dataSource === "live" && ENABLE_DECISION_TOOLS ? (
              <div className="feature-panels">
                <EligibilityPanel />
                <ChangesPanel />
              </div>
            ) : null}

            {/* 주거 사업 카드 영역 */}
            <div className="result-heading">
              <h2>조건에 맞는 추천 주거사업 {result.recommendations.length}개</h2>
            </div>

            <div className="cards">
              {sortedRecommendations.map((program, index) => (
                <ProgramCard program={program} index={index} key={program.id} />
              ))}
            </div>
          </section>
        )}

        {/* 결과가 없을 때의 기본 가이드 화면 */}
        {!result && !isChatActive && (
          <section className="empty-state">
            <p>아래 예시 질문을 누르시거나 궁금한 내용을 직접 입력하세요.</p>
          </section>
        )}

        {/* 제미나이 캡슐 입력 바 패널 */}
        <section className={`input-panel ${isChatActive ? "fixed-bottom" : ""}`}>
          <form onSubmit={handleSubmit} className="search-form">

            {/* 좌측 플러스 버튼 */}
            <button type="button" className="input-plus-btn" title="추가 기능" aria-label="추가 기능">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
            </button>

            {/* 검색 에어리어 */}
            <textarea
              ref={textareaRef}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              aria-label="주거 상황 입력"
              placeholder="청주나AI에게 물어보기"
              rows={1}
              onKeyDown={(event) => {
                // 엔터키 입력 시 전송 (Shift+Enter는 줄바꿈)
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />

            {/* 우측 도구 바 */}
            <div className="form-actions">
              {/* 마이크 아이콘 */}
              <button type="button" className="mic-btn" title="음성 입력" aria-label="음성 입력">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                  <path d="M19 10v1a7 7 0 0 1-14 0v-1"></path>
                  <line x1="12" y1="19" x2="12" y2="22"></line>
                </svg>
              </button>

              {/* 전송 버튼 */}
              <button className="primary-button" type="submit" disabled={isLoading || !message.trim()} title="전송" aria-label="전송">
                {isLoading ? (
                  // 로딩 회전 애니메이션
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" style={{ animation: "spin 1s linear infinite" }}>
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25"></circle>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor"></path>
                  </svg>
                ) : (
                  // 전송 화살표
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" style={{ transform: "rotate(0deg)" }}>
                    <line x1="12" y1="19" x2="12" y2="5"></line>
                    <polyline points="5 12 12 5 19 12"></polyline>
                  </svg>
                )}
              </button>
            </div>
          </form>

          {/* 첫 접속 상태에서 인풋창 하단에 예시 캡슐 버튼 표출 */}
          {!isChatActive && (
            <div className="prompt-buttons" aria-label="예시 입력">
              {SAMPLE_PROMPTS.map((prompt, index) => (
                <button
                  key={prompt}
                  type="button"
                  title={prompt}
                  onClick={() => setMessage(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          )}

          {error ? <p className="error">{error}</p> : null}
        </section>

      </section>

      {/* 로딩 애니메이션 스타일 키프레임 정의용 */}
      <style jsx global>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </main>
  );
}
