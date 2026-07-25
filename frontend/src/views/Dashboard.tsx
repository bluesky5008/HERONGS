import { useEffect, useState } from "react";
import { api, RecItem } from "../api";
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
    try {
      await api.runScan(); // AC-02: 시장 스캔 실행
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
