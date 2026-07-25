import { RecItem } from "../api";

const GROUP_LABELS: Record<string, string> = {
  value: "가치",
  quality: "퀄리티",
  trend: "추세",
  supply: "수급",
  momentum: "모멘텀",
  risk: "리스크",
  rt_momentum: "실시간모멘텀",
  strength: "체결",
};

/** 점수 구성 표시 (FR-05: 어떤 지표가 몇 점을 기여했는지) */
export function ScoreBreakdown({ breakdown }: { breakdown: RecItem["breakdown"] }) {
  return (
    <div className="breakdown">
      {Object.entries(breakdown).map(([group, b]) => (
        <div key={group}>
          <div className="bar-row">
            <span className="label">{GROUP_LABELS[group] ?? group}</span>
            <div className="bar">
              <div style={{ width: `${b.weight ? (b.points / b.weight) * 100 : 0}%` }} />
            </div>
            <span>
              {b.points}/{b.weight}
            </span>
          </div>
          <div className="muted" style={{ marginLeft: 98, fontSize: 11 }}>
            {Object.entries(b.details)
              .filter(([, v]) => v !== null && v !== undefined)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")}
          </div>
        </div>
      ))}
    </div>
  );
}
