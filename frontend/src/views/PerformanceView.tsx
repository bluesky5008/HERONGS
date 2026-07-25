import { useEffect, useState } from "react";
import { api, Performance } from "../api";

const PROFILE_LABELS: Record<string, string> = { long: "장기", swing: "스윙", scalp: "단타" };

/** 추천 이력·전략별 적중률 리포트 (FR-16, AC-09) */
export function PerformanceView() {
  const [data, setData] = useState<Performance | null>(null);

  useEffect(() => {
    api.performance().then(setData);
  }, []);

  if (!data) return <div className="card muted">불러오는 중…</div>;

  return (
    <>
      <div className="card">
        <div className="title" style={{ marginBottom: 8 }}>전략별 성과</div>
        {Object.keys(data.report).length === 0 && (
          <div className="muted">평가된 추천이 아직 없습니다 (1영업일 경과 후 집계).</div>
        )}
        <table className="list">
          <thead>
            <tr><th>전략</th><th>구간</th><th>건수</th><th>적중률</th><th>평균수익</th></tr>
          </thead>
          <tbody>
            {Object.entries(data.report).flatMap(([profile, horizons]) =>
              Object.entries(horizons).map(([h, r]) => (
                <tr key={`${profile}-${h}`}>
                  <td>{PROFILE_LABELS[profile] ?? profile}</td>
                  <td>{h}일</td>
                  <td>{r.count}</td>
                  <td>{r.hit_rate}%</td>
                  <td className={r.avg_return >= 0 ? "up" : "down"}>
                    {r.avg_return >= 0 ? "+" : ""}{r.avg_return}%
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="title" style={{ marginBottom: 8 }}>추천 이력</div>
        <table className="list">
          <thead>
            <tr><th>일시</th><th>전략</th><th>종목</th><th>점수</th><th>1d</th><th>5d</th><th>20d</th></tr>
          </thead>
          <tbody>
            {data.history.map((h) => (
              <tr key={h.id}>
                <td className="muted">{new Date(h.ts).toLocaleDateString("ko-KR")}</td>
                <td>{PROFILE_LABELS[h.profile] ?? h.profile}</td>
                <td>{h.code}</td>
                <td>{h.score}</td>
                {[1, 5, 20].map((d) => {
                  const r = h.returns[d];
                  return (
                    <td key={d} className={r === undefined ? "muted" : r >= 0 ? "up" : "down"}>
                      {r === undefined ? "–" : `${r >= 0 ? "+" : ""}${r}%`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
