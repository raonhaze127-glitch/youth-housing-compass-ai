"use client";

import { useState } from "react";

type ChangeItem = {
  id: string;
  type: "new" | "updated" | "removed";
  detected_at?: string;
  name?: string;
  region?: string;
  field_changes?: Record<string, { before?: unknown; after?: unknown }>;
};

const TYPE_LABEL = {
  new: "신규",
  updated: "수정",
  removed: "마감·삭제"
};

export function ChangesPanel() {
  const [items, setItems] = useState<ChangeItem[] | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadChanges() {
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch("/api/changes?limit=10");
      const payload = (await response.json()) as {
        changes?: ChangeItem[];
        tracking_status?: string;
        detail?: string;
        error?: string;
      };
      if (!response.ok) throw new Error(payload.detail ?? payload.error ?? "변동 이력을 불러오지 못했습니다.");
      setItems(payload.changes ?? []);
      if (payload.tracking_status === "bootstrap_no_diff_yet") {
        setMessage("변동 추적이 시작된 단계라 아직 비교 결과가 없습니다.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "변동 이력을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="changes-panel">
      <div>
        <p className="section-label">공고 변동 추적</p>
        <h2>최근 신규·수정·마감 공고</h2>
      </div>
      <button className="secondary-action changes-button" type="button" onClick={loadChanges} disabled={loading}>
        {loading ? "확인 중" : "최근 변동 확인"}
      </button>
      {message ? <p className="changes-message">{message}</p> : null}
      {items ? (
        items.length ? (
          <ul className="changes-list">
            {items.map((item) => (
              <li key={`${item.type}-${item.id}-${item.detected_at}`}>
                <span className={`change-type ${item.type}`}>{TYPE_LABEL[item.type]}</span>
                <div>
                  <strong>{item.name ?? item.id}</strong>
                  <small>{[item.region, item.detected_at].filter(Boolean).join(" · ")}</small>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="changes-message">최근 기록된 변동이 없습니다.</p>
        )
      ) : null}
    </section>
  );
}
