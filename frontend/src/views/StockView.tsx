import { useEffect, useRef, useState } from "react";
import { createChart, IChartApi } from "lightweight-charts";
import { api, Candle, OpinionItem } from "../api";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { OrderDialog } from "./OrderDialog";
import { regimeLabel } from "../App";

const PROFILE_LABELS: Record<string, string> = { long: "장기", swing: "스윙", scalp: "단타" };
const STANCE_LABELS: Record<string, string> = {
  buy: "매수", sell: "매도", hold: "홀딩", watch: "관망", avoid: "비추천",
};

/** 개별 종목 분석 — 3개 전략 관점 의견 + 근거 + 차트 (FR-06/07, AC-03) */
export function StockView({ code, onCode }: { code: string; onCode: (c: string) => void }) {
  const [input, setInput] = useState(code);
  const [opinions, setOpinions] = useState<OpinionItem[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [order, setOrder] = useState<{ side: "buy" | "sell"; profile: string } | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  const analyze = async (c: string) => {
    if (!c) return;
    setLoading(true);
    setError("");
    try {
      const [ops, prices] = await Promise.all([api.analysis(c), api.prices(c)]);
      setOpinions(ops);
      setCandles(prices);
      onCode(c);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (code) analyze(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  useEffect(() => {
    if (!chartRef.current || candles.length === 0) return;
    const chart: IChartApi = createChart(chartRef.current, {
      height: 260,
      layout: { background: { color: "#1f2937" }, textColor: "#9ca3af" },
      grid: { vertLines: { color: "#374151" }, horzLines: { color: "#374151" } },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#ef4444", downColor: "#3b82f6",
      wickUpColor: "#ef4444", wickDownColor: "#3b82f6", borderVisible: false,
    });
    series.setData(candles);
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: chartRef.current?.clientWidth ?? 0 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [candles]);

  const name = opinions[0]?.name || "";

  return (
    <>
      <div className="formrow">
        <input
          placeholder="종목코드 입력 (예: 005930)"
          value={input}
          onChange={(e) => setInput(e.target.value.trim())}
          onKeyDown={(e) => e.key === "Enter" && analyze(input)}
        />
        <button className="ghost" onClick={() => analyze(input)} disabled={loading}>
          {loading ? "분석 중…" : "분석"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {name && (
        <div className="card row">
          <span className="title">{name} ({opinions[0].code})</span>
          <span>
            <button className="ghost" onClick={() => api.addWatch(opinions[0].code)}>☆ 관심</button>{" "}
            <button className="ghost" onClick={() => setOrder({ side: "buy", profile: "swing" })}>매수</button>{" "}
            <button className="ghost" onClick={() => setOrder({ side: "sell", profile: "swing" })}>매도</button>
          </span>
        </div>
      )}
      {candles.length > 0 && <div className="card"><div ref={chartRef} /></div>}
      {opinions.map((op) => (
        <div className="card" key={op.profile}>
          <div className="row">
            <span className="title">{PROFILE_LABELS[op.profile] ?? op.profile}</span>
            <span>
              <span className="score" style={{ marginRight: 8 }}>{op.score}점</span>
              <span className={`stance ${op.stance}`}>{STANCE_LABELS[op.stance] ?? op.stance}</span>
            </span>
          </div>
          <div className="muted">
            국면 {regimeLabel(op.regime)}
            {op.override && ` · 우선규칙: ${op.override}`}
          </div>
          {op.holding && (
            <div className="muted">
              보유 {op.holding.qty}주 @ {op.holding.avg_price.toLocaleString()}원 (
              <span className={op.holding.pnl_pct >= 0 ? "up" : "down"}>{op.holding.pnl_pct}%</span>
              ) · 손절 {op.holding.stop_price?.toLocaleString()} / 목표 {op.holding.target_price?.toLocaleString()}
            </div>
          )}
          <ScoreBreakdown breakdown={op.score_breakdown} />
        </div>
      ))}
      {order && name && (
        <OrderDialog
          side={order.side}
          code={opinions[0].code}
          name={name}
          profile={order.profile}
          onClose={() => setOrder(null)}
        />
      )}
    </>
  );
}
