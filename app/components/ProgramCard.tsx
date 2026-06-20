"use client";

import { useEffect, useState } from "react";
import { ApplicationStatusBadge } from "./ApplicationStatusBadge";
import { getBrowserUserId } from "@/lib/browser-user";
import type { Recommendation } from "@/lib/types";

type Insight = {
  title: string;
  body: string;
  note?: string;
};

const FAVORITES_KEY = "youth-housing-compass:favorites";

function readFavorites() {
  try {
    return new Set<string>(JSON.parse(localStorage.getItem(FAVORITES_KEY) ?? "[]"));
  } catch {
    return new Set<string>();
  }
}

function rawInsight(payload: Record<string, unknown>): Insight {
  const sections = (payload.sections ?? {}) as Record<string, unknown>;
  const preferred = sections["자격"] ?? sections["공급대상"] ?? payload.text;
  const body = typeof preferred === "string" ? preferred.slice(0, 900) : "추출된 자격 섹션이 없습니다.";
  return {
    title: "공고 해석",
    body,
    note: payload.truncated ? "원문 일부만 추출됐습니다. 원문을 함께 확인해주세요." : undefined
  };
}

function competitionInsight(payload: Record<string, unknown>): Insight {
  const nested = (payload.result ?? payload.competition ?? payload) as Record<string, unknown>;
  const rate = nested.competition_rate ?? nested.avg_rate;
  const source = String(nested.source ?? payload.source ?? "확인 불가");
  const cutoff = nested.cutoff_avg ?? nested.avg_cutoff_score;
  const body = rate
    ? `경쟁률 ${rate}:1${cutoff ? ` · 평균 당첨가점 ${cutoff}점` : ""}`
    : "확인 가능한 경쟁률 데이터가 없습니다.";
  return {
    title: "경쟁률",
    body,
    note: String(nested.disclaimer ?? payload.disclaimer ?? `출처: ${source}`)
  };
}

export function ProgramCard({ program, index }: { program: Recommendation; index: number }) {
  const [favorite, setFavorite] = useState(false);
  const [favoriteLoading, setFavoriteLoading] = useState(false);
  const [insight, setInsight] = useState<Insight | null>(null);
  const [loadingAction, setLoadingAction] = useState<"raw" | "competition" | null>(null);
  const sourceId = program.source_id ?? program.id;
  const hasLiveFeatures = program.source_type === "k_apt_alert_proxy";

  useEffect(() => {
    if (!hasLiveFeatures) {
      setFavorite(readFavorites().has(program.id));
      return;
    }
    const userId = getBrowserUserId();
    fetch(`/api/users/${encodeURIComponent(userId)}/favorites`)
      .then((response) => response.json())
      .then((payload: { favorites?: Array<{ announcement_id: string }> }) => {
        setFavorite(Boolean(payload.favorites?.some((item) => item.announcement_id === program.id)));
      })
      .catch(() => setFavorite(readFavorites().has(program.id)));
  }, [hasLiveFeatures, program.id]);

  async function toggleFavorite() {
    if (hasLiveFeatures) {
      setFavoriteLoading(true);
      try {
        const userId = getBrowserUserId();
        const response = await fetch(
          `/api/users/${encodeURIComponent(userId)}/favorites/${encodeURIComponent(program.id)}`,
          {
            method: favorite ? "DELETE" : "PUT",
            headers: favorite ? undefined : { "Content-Type": "application/json" },
            body: favorite ? undefined : JSON.stringify(program)
          }
        );
        if (!response.ok) throw new Error("관심 공고 저장에 실패했습니다.");
        setFavorite(!favorite);
        return;
      } catch {
        // 서버 저장이 불가능한 경우 브라우저 저장으로 이어갑니다.
      } finally {
        setFavoriteLoading(false);
      }
    }
    const favorites = readFavorites();
    if (favorites.has(program.id)) favorites.delete(program.id);
    else favorites.add(program.id);
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favorites]));
    setFavorite(favorites.has(program.id));
  }

  async function loadInsight(kind: "raw" | "competition") {
    setLoadingAction(kind);
    setInsight(null);
    try {
      const response = await fetch(
        `/api/announcements/${encodeURIComponent(sourceId)}/${kind}`
      );
      const payload = (await response.json()) as Record<string, unknown> & {
        detail?: string;
        error?: string;
      };
      if (!response.ok) throw new Error(payload.detail ?? payload.error ?? "정보를 불러오지 못했습니다.");
      setInsight(kind === "raw" ? rawInsight(payload) : competitionInsight(payload));
    } catch (error) {
      setInsight({
        title: kind === "raw" ? "공고 해석" : "경쟁률",
        body: error instanceof Error ? error.message : "정보를 불러오지 못했습니다."
      });
    } finally {
      setLoadingAction(null);
    }
  }

  return (
    <article className="program-card">
      <div className="card-head">
        <span className="rank">{index + 1}</span>
        <div>
          <div className="card-meta">
            <p>{program.organization}</p>
            <ApplicationStatusBadge status={program.status} />
          </div>
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
            {program.apply_start && program.apply_end
              ? `${program.apply_start} ~ ${program.apply_end}`
              : "일정 확인 필요"}
          </dd>
        </div>
        <div>
          <dt>지원내용</dt>
          <dd>{program.benefit_summary || program.eligibility_summary}</dd>
        </div>
      </dl>

      {insight ? (
        <div className="insight-box" aria-live="polite">
          <strong>{insight.title}</strong>
          <p>{insight.body}</p>
          {insight.note ? <small>{insight.note}</small> : null}
        </div>
      ) : null}

      <div className="card-actions">
        <button type="button" className="secondary-action" onClick={toggleFavorite} disabled={favoriteLoading}>
          {favoriteLoading ? "저장 중" : favorite ? "관심 해제" : "관심 저장"}
        </button>
        {hasLiveFeatures ? (
          <>
            <button
              type="button"
              className="secondary-action"
              onClick={() => loadInsight("raw")}
              disabled={loadingAction !== null}
            >
              {loadingAction === "raw" ? "분석 중" : "공고 해석"}
            </button>
            <button
              type="button"
              className="secondary-action"
              onClick={() => loadInsight("competition")}
              disabled={loadingAction !== null}
            >
              {loadingAction === "competition" ? "조회 중" : "경쟁률"}
            </button>
            <a
              className="secondary-link"
              href={`/api/announcements/${encodeURIComponent(sourceId)}/calendar`}
            >
              일정 저장
            </a>
          </>
        ) : null}
        <a className="primary-link" href={program.announcement_url} target="_blank" rel="noreferrer">
          원문 확인
        </a>
      </div>
    </article>
  );
}
