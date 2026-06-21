"use client";

import { FormEvent, useEffect, useState } from "react";
import { getBrowserUserId } from "@/lib/browser-user";

type ScoreResult = {
  scores?: {
    no_house?: number;
    family?: number;
    account?: number;
    total?: number;
    max_total?: number;
  };
  specials?: Record<string, unknown>;
  error?: string;
  detail?: string;
};

function eligibleSpecials(specials: Record<string, unknown> | undefined) {
  if (!specials) return [];
  return Object.entries(specials)
    .filter(([, value]) => {
      if (typeof value === "boolean") return value;
      if (value && typeof value === "object") {
        return Boolean((value as Record<string, unknown>).eligible);
      }
      return false;
    })
    .map(([key]) => key);
}

export function EligibilityPanel() {
  const [age, setAge] = useState(28);
  const [noHouseYears, setNoHouseYears] = useState(0);
  const [dependents, setDependents] = useState(0);
  const [accountYears, setAccountYears] = useState(0);
  const [depositCount, setDepositCount] = useState(0);
  const [everOwnedHouse, setEverOwnedHouse] = useState(false);
  const [noHouse, setNoHouse] = useState(true);
  const [marriageDate, setMarriageDate] = useState("");
  const [minorChildren, setMinorChildren] = useState(0);
  const [previousWin, setPreviousWin] = useState("없음");
  const [result, setResult] = useState<ScoreResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const userId = getBrowserUserId();
    fetch(`/api/users/${encodeURIComponent(userId)}/profile`)
      .then(async (response) => (response.ok ? response.json() : null))
      .then((payload: { profile?: Record<string, unknown> } | null) => {
        const profile = payload?.profile;
        if (!profile) return;
        const account = (profile.subscription_account ?? {}) as Record<string, unknown>;
        setAge(Number(profile.age ?? 28));
        setNoHouseYears(Number(profile.no_house_years ?? 0));
        setDependents(Number(profile.dependents ?? 0));
        setAccountYears(Number(account.years ?? 0));
        setDepositCount(Number(account.deposit_count ?? 0));
        setEverOwnedHouse(Boolean(profile.ever_owned_house));
        setNoHouse(profile.no_house !== false);
        setMarriageDate(String(profile.marriage_date ?? ""));
        setMinorChildren(Array.isArray(profile.children) ? profile.children.length : 0);
        setPreviousWin(String(profile.previous_win ?? "없음"));
      })
      .catch(() => undefined);
  }, []);

  async function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setResult(null);
    const profile = {
      age,
      no_house_years: noHouseYears,
      dependents,
      no_house: noHouse,
      ever_owned_house: everOwnedHouse,
      marriage_date: marriageDate || undefined,
      children: Array.from({ length: minorChildren }, () => ({ age: 0 })),
      previous_win: previousWin,
      subscription_account: {
        years: accountYears,
        deposit_count: depositCount
      }
    };
    try {
      const userId = getBrowserUserId();
      await fetch(`/api/users/${encodeURIComponent(userId)}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile)
      });
      const response = await fetch("/api/eligibility/score", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile
        })
      });
      const payload = (await response.json()) as ScoreResult;
      if (!response.ok) throw new Error(payload.detail ?? payload.error ?? "사전 점검에 실패했습니다.");
      setResult(payload);
    } catch (error) {
      setResult({ error: error instanceof Error ? error.message : "사전 점검에 실패했습니다." });
    } finally {
      setLoading(false);
    }
  }

  const specials = eligibleSpecials(result?.specials);

  return (
    <section className="eligibility-panel">
      <div>
        <p className="section-label">청약 자격·가점 사전 점검</p>
        <h2>내 조건을 숫자로 확인해보세요</h2>
        <p>계산 결과는 참고용이며 실제 자격은 공고문과 청약홈에서 확정해야 합니다.</p>
      </div>
      <form className="eligibility-form" onSubmit={calculate}>
        <label>
          만 나이
          <input type="number" min="18" max="100" value={age} onChange={(event) => setAge(Number(event.target.value))} />
        </label>
        <label>
          무주택 기간(년)
          <input type="number" min="0" max="50" value={noHouseYears} onChange={(event) => setNoHouseYears(Number(event.target.value))} />
        </label>
        <label>
          부양가족 수
          <input type="number" min="0" max="10" value={dependents} onChange={(event) => setDependents(Number(event.target.value))} />
        </label>
        <label>
          통장 가입기간(년)
          <input type="number" min="0" max="50" value={accountYears} onChange={(event) => setAccountYears(Number(event.target.value))} />
        </label>
        <label>
          납입횟수
          <input type="number" min="0" max="600" value={depositCount} onChange={(event) => setDepositCount(Number(event.target.value))} />
        </label>
        <label>
          혼인신고일(해당 시)
          <input type="date" value={marriageDate} onChange={(event) => setMarriageDate(event.target.value)} />
        </label>
        <label>
          미성년 자녀 수
          <input type="number" min="0" max="10" value={minorChildren} onChange={(event) => setMinorChildren(Number(event.target.value))} />
        </label>
        <label>
          과거 당첨 이력
          <select value={previousWin} onChange={(event) => setPreviousWin(event.target.value)}>
            <option value="없음">없음</option>
            <option value="있음">있음</option>
          </select>
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={noHouse} onChange={(event) => setNoHouse(event.target.checked)} />
          현재 무주택
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={everOwnedHouse} onChange={(event) => setEverOwnedHouse(event.target.checked)} />
          과거 주택 소유 이력 있음
        </label>
        <button className="primary-button" type="submit" disabled={loading}>
          {loading ? "계산 중" : "가점 계산"}
        </button>
      </form>
      {result?.error ? <p className="error">{result.error}</p> : null}
      {result?.scores ? (
        <div className="score-result" aria-live="polite">
          <strong>{result.scores.total}점 / {result.scores.max_total ?? 84}점</strong>
          <span>무주택 {result.scores.no_house} · 부양가족 {result.scores.family} · 통장 {result.scores.account}</span>
          <span>{specials.length ? `가능성 있는 특별공급: ${specials.join(", ")}` : "특별공급은 추가 조건 확인이 필요합니다."}</span>
        </div>
      ) : null}
    </section>
  );
}
