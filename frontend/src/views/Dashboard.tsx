import { useEffect, useState } from "react";
import { api, ApiError, RecItem } from "../api";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { OrderDialog } from "./OrderDialog";

const PROFILES = [
  { key: "long", label: "장기" },
  { key: "swing", label: "스윙" },
  { key: "scalp", label: "단타" },
];

export function Dashboard({
  onSelect,
  onScanned,
}: {
  onSelect: (code: string) => void;
  onScanned: () => void;
}) {
  const [profile, setProfile] = useState("swing");
  const [items, setItems] = useState<RecItem[]>([]);
  const [ts, setTs] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [orderTarget, setOrderTarget] = useState<RecItem | null>(null);

  const load = (p: string) => {
    api.recommendations(p).then((r) => {
      setItems(r.items);
      setTs(r.ts);
    });
  };
  useEffect(() => load(profile), [profile]);

  const runScan = async () => {
    setScanning(true);
    setScanError(null);
    try {
      // AC-02: 시장 스캔 실행. 이미 진행 중(409)이면 그 스캔이 끝나기를 기다린다
      await api.runScan().catch((e) => {
        if (!(e instanceof ApiError && e.status === 409)) throw e;
      });
      // 스캔은 백그라운드로 돈다(수 분) — 끝날 때까지 5초 간격으로 확인 (DCR-005)
      let status = await api.scanStatus();
      while (status.running) {
        await new Promise((r) => setTimeout(r, 5000));
        status = await api.scanStatus();
      }
      if (status.error) setScanError(status.error);
      load(profile);
      onScanned();
    } finally {
      setScanning(false);
    }
  };

  return (
    <>
      <div className="tabs">
        {PROFILES.map((p) => (
          <button key={p.key} className={profile === p.key ? "active" : ""} onClick={() => setProfile(p.key)}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="card row" style={{ display: "flex" }}>
        <span className="muted">{ts ? `스캔: ${new Date(ts).toLocaleString("ko-KR")}` : "스캔 이력 없음"}</span>
        <button className="ghost" onClick={runScan} disabled={scanning}>
          {scanning ? "스캔 중…" : "시장 스캔 실행"}
        </button>
      </div>
      {scanError && <div className="card muted">스캔 실패: {scanError}</div>}
      {items.length === 0 && <div className="card muted">추천 없음 — 스캔을 실행해 보세요.</div>}
      {items.map((it) => (
        <div className="card" key={it.code}>
          <div className="row">
            <div onClick={() => onSelect(it.code)} style={{ cursor: "pointer" }}>
              <span className="title">
                {it.rank}. {it.name || it.code}
              </span>
              <div className="muted">{it.code}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="score">{it.score}점</div>
              <button className="ghost" onClick={() => setExpanded(expanded === it.code ? null : it.code)}>
                근거
              </button>{" "}
              <button className="ghost" onClick={() => setOrderTarget(it)}>
                매수
              </button>
            </div>
          </div>
          {expanded === it.code && <ScoreBreakdown breakdown={it.breakdown} />}
        </div>
      ))}
      {orderTarget && (
        <OrderDialog
          side="buy"
          code={orderTarget.code}
          name={orderTarget.name}
          profile={profile}
          onClose={() => setOrderTarget(null)}
        />
      )}
    </>
  );
}
