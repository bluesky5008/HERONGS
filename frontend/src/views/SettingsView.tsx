import { useEffect, useState } from "react";
import { api, AppSettings, Condition, WatchItem } from "../api";

/** 설정 — 조건식 매핑(FR-13, AC-08), 관심종목(FR-10), 거래 모드 확인 */
export function SettingsView() {
  const [conditions, setConditions] = useState<Condition[]>([]);
  const [watch, setWatch] = useState<WatchItem[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [busy, setBusy] = useState(false);

  const load = (refresh = false) => {
    api.conditions(refresh).then(setConditions);
    api.watchlist().then(setWatch);
    api.settings().then(setSettings);
  };
  useEffect(() => load(), []);

  const refreshConditions = async () => {
    setBusy(true);
    try {
      load(true); // HTS 등록 조건식 재조회 (ka10171)
    } finally {
      setBusy(false);
    }
  };

  const setProfile = async (c: Condition, profile: string) => {
    await api.mapCondition(c.seq, profile, c.enabled);
    load();
  };

  return (
    <>
      {settings && (
        <div className="card">
          <div className="row">
            <span className="title">거래 모드</span>
            <span className={`badge ${settings.trading_mode}`}>
              {settings.trading_mode === "mock" ? "모의투자" : "실계좌"}
            </span>
          </div>
          <div className="muted" style={{ marginTop: 6 }}>
            실계좌 전환은 서버 .env(HERONGS_TRADING_MODE=real)에서만 가능합니다 (NFR-02).
          </div>
          <div className="muted">
            1회 주문 상한 {settings.max_order_amount.toLocaleString()}원 · 일일 상한{" "}
            {settings.daily_order_limit.toLocaleString()}원
          </div>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <span className="title">조건검색식 → 전략 매핑</span>
          <button className="ghost" onClick={refreshConditions} disabled={busy}>
            HTS 목록 새로고침
          </button>
        </div>
        {conditions.length === 0 && (
          <div className="muted">
            조건식 없음 — 영웅문 HTS [0150]에서 HERONGS_ 조건식을 만들어 서버 저장하세요 (D-07).
          </div>
        )}
        {conditions.map((c) => (
          <div className="row" key={c.seq} style={{ marginBottom: 6 }}>
            <span>{c.name}</span>
            <select
              value={c.profile}
              onChange={(e) => setProfile(c, e.target.value)}
              style={{ width: 120 }}
            >
              <option value="">미사용</option>
              <option value="long">장기</option>
              <option value="swing">스윙</option>
              <option value="scalp">단타</option>
            </select>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="title" style={{ marginBottom: 8 }}>관심종목</div>
        {watch.length === 0 && <div className="muted">관심종목 없음</div>}
        {watch.map((w) => (
          <div className="row" key={w.code} style={{ marginBottom: 6 }}>
            <span>
              {w.name || w.code} <span className="muted">({w.group})</span>
            </span>
            <button className="ghost" onClick={() => api.removeWatch(w.code).then(() => load())}>
              삭제
            </button>
          </div>
        ))}
      </div>
    </>
  );
}
