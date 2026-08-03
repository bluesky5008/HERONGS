import { useEffect, useState } from "react";
import { api, OpenOrder, Portfolio } from "../api";

const STANCE_SHORT: Record<string, string> = {
  buy: "매수", sell: "매도", hold: "홀딩", watch: "관망", avoid: "비추",
};
const PROFILE_LABELS: Record<string, string> = { long: "장기", swing: "스윙", scalp: "단타" };

/** 잔고·수익률·보유종목 의견 + 미체결 (FR-07/09) */
export function PortfolioView({ onSelect }: { onSelect: (code: string) => void }) {
  const [pf, setPf] = useState<Portfolio | null>(null);
  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [error, setError] = useState("");

  const load = () => {
    api.portfolio().then(setPf).catch((e) => setError(String(e)));
    api.openOrders().then(setOrders).catch(() => undefined);
  };
  useEffect(load, []);

  const cancel = async (o: OpenOrder) => {
    await api.cancelOrder(o.ord_no, o.code);
    load();
  };

  if (error) return <div className="error">{error}</div>;
  if (!pf) return <div className="card muted">불러오는 중…</div>;

  return (
    <>
      <div className="card">
        <div className="row">
          <span className="muted">평가금액</span>
          <span className="title">{pf.total_eval.toLocaleString()}원</span>
        </div>
        <div className="row">
          <span className="muted">평가손익</span>
          <span className={pf.total_pnl >= 0 ? "up" : "down"}>
            {pf.total_pnl >= 0 ? "+" : ""}
            {pf.total_pnl.toLocaleString()}원 ({pf.total_pnl_pct}%)
          </span>
        </div>
      </div>

      <div className="card">
        <div className="title" style={{ marginBottom: 8 }}>보유 종목</div>
        {pf.stocks.length === 0 && <div className="muted">보유 종목 없음</div>}
        <table className="list">
          <tbody>
            {pf.stocks.map((s) => (
              <tr key={s.code} onClick={() => onSelect(s.code)} style={{ cursor: "pointer" }}>
                <td>
                  <div className="title">{s.name || s.code}</div>
                  <div className="muted">
                    {s.qty}주 @ {s.avg_price.toLocaleString()}
                  </div>
                </td>
                <td style={{ textAlign: "right" }}>
                  <div className={s.pnl >= 0 ? "up" : "down"}>
                    {s.pnl_pct >= 0 ? "+" : ""}
                    {s.pnl_pct}%
                  </div>
                  <div className="muted">
                    {s.opinions &&
                      Object.entries(s.opinions)
                        .map(([p, st]) => `${PROFILE_LABELS[p] ?? p}:${STANCE_SHORT[st] ?? st}`)
                        .join(" ")}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <span className="title">미체결</span>
          <button className="ghost" onClick={load}>새로고침</button>
        </div>
        {orders.length === 0 && <div className="muted">미체결 없음</div>}
        <table className="list">
          <tbody>
            {orders.map((o) => (
              <tr key={o.ord_no}>
                <td>
                  <div className="title">{o.name || o.code}</div>
                  <div className="muted">
                    {o.side} {o.qty}주 @ {o.price.toLocaleString()} (미체결 {o.unfilled_qty})
                  </div>
                </td>
                <td style={{ textAlign: "right" }}>
                  <button className="ghost" onClick={() => cancel(o)}>취소</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
