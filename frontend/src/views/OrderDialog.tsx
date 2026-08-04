import { useEffect, useRef, useState } from "react";
import { api, ApiError, Preview, Quote } from "../api";

const REFRESH_MS = 3000; // 자동 갱신 주기 (FR-24, NFR-08)
const IDLE_MS = 180000; // 무입력 3분 후 갱신 중지
const MAX_FAILS = 3; // 연속 실패 시 중지

/** 주문 확인 다이얼로그 — preview 승인 없이 전송 경로 없음 (FR-08, AC-04/10) */
export function OrderDialog({
  side,
  code,
  name,
  profile,
  onClose,
}: {
  side: "buy" | "sell";
  code: string;
  name: string;
  profile: string;
  onClose: () => void;
}) {
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [paused, setPaused] = useState(false);
  const idleUntil = useRef(0);
  const fails = useRef(0);

  /** 계좌 정보는 주문 전에는 변하지 않으므로 갱신 시 시세·호가만 받는다 (NFR-08). */
  const loadQuote = async (withAccount: boolean): Promise<boolean> => {
    try {
      const q = await api.quote(code, withAccount);
      setQuote((prev) =>
        withAccount || !prev
          ? q
          : { ...q, holding_qty: prev.holding_qty, orderable_cash: prev.orderable_cash },
      );
      return true;
    } catch {
      return false; // 갱신 실패는 직전 값을 유지한다
    }
  };

  const keepAlive = () => {
    idleUntil.current = Date.now() + IDLE_MS;
  };

  const resume = () => {
    fails.current = 0;
    keepAlive();
    setPaused(false);
    loadQuote(true);
  };

  useEffect(() => {
    keepAlive();
    loadQuote(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  // 입력 단계에서만 자동 갱신. 확인 단계 진입·방치·화면 비활성에서 멈춘다 (FR-24)
  useEffect(() => {
    if (preview || done || paused) return;
    const id = setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() > idleUntil.current) {
        setPaused(true);
        return;
      }
      fails.current = (await loadQuote(false)) ? 0 : fails.current + 1;
      if (fails.current >= MAX_FAILS) setPaused(true);
    }, REFRESH_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, done, paused, code]);

  const doPreview = async () => {
    setError("");
    setBusy(true);
    try {
      setPreview(
        await api.previewOrder({
          side,
          code,
          qty: Number(qty),
          price: Number(price),
          profile,
        }),
      );
    } catch (e) {
      // 가드레일 차단 사유 표시 (AC-10)
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const doConfirm = async () => {
    if (!preview) return;
    setError("");
    setBusy(true);
    try {
      const r = await api.confirmOrder(preview.preview_id);
      setDone(`주문 접수 완료 (주문번호 ${r.ord_no})`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setPreview(null); // preview 만료·재사용 → 다시 확인
      keepAlive(); // 입력 단계로 되돌아온 시점부터 방치 시간을 다시 센다
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h3>
          {name || code} {side === "buy" ? "매수" : "매도"}
        </h3>
        {done ? (
          <>
            <p>{done}</p>
            <button className="primary" onClick={onClose}>
              닫기
            </button>
          </>
        ) : preview ? (
          <>
            {/* 확인 단계: 수량·가격·예상금액·비중·손절/목표 (FR-08/15) */}
            <table>
              <tbody>
                <tr><td>모드</td><td><span className={`badge ${preview.trading_mode}`}>{preview.trading_mode === "mock" ? "모의투자" : "실계좌"}</span></td></tr>
                <tr><td>수량</td><td>{preview.qty.toLocaleString()}주</td></tr>
                <tr><td>가격</td><td>{preview.price.toLocaleString()}원</td></tr>
                <tr><td>예상금액</td><td>{preview.amount.toLocaleString()}원</td></tr>
                {preview.weight_pct !== null && (
                  <tr><td>계좌 대비 비중</td><td>{preview.weight_pct}%</td></tr>
                )}
                <tr><td>제안 손절가</td><td>{preview.suggested_stop.toLocaleString()}원</td></tr>
                <tr><td>제안 목표가</td><td>{preview.suggested_target.toLocaleString()}원</td></tr>
              </tbody>
            </table>
            {error && <div className="error">{error}</div>}
            <button className={`primary ${side === "buy" ? "danger" : ""}`} onClick={doConfirm} disabled={busy}>
              승인하고 주문 전송
            </button>
            <button className="ghost" style={{ width: "100%", marginTop: 8 }} onClick={() => { setPreview(null); keepAlive(); }}>
              돌아가기
            </button>
          </>
        ) : (
          <>
            {/* 입력 보조 정보 — 현재가·계좌·호가 (FR-20/21/22) */}
            <div className="quote">
              <div className="row">
                <span>
                  현재가{" "}
                  <b>{quote?.cur_price ? quote.cur_price.toLocaleString() : "—"}</b>{" "}
                  {quote?.change_rate != null && (
                    <span className={quote.change_rate >= 0 ? "up" : "down"}>
                      ({quote.change_rate >= 0 ? "+" : ""}
                      {quote.change_rate}%)
                    </span>
                  )}
                </span>
                {paused ? (
                  <button className="ghost" onClick={resume}>갱신 멈춤 · 재개</button>
                ) : (
                  <span className="muted">자동 갱신 중</span>
                )}
              </div>
              <div className="row muted">
                {side === "buy"
                  ? `주문가능 ${quote?.orderable_cash != null ? quote.orderable_cash.toLocaleString() + "원" : "—"}`
                  : `보유 ${quote?.holding_qty != null ? quote.holding_qty.toLocaleString() + "주" : "—"}`}
                {quote?.orderbook && <span>호가 {quote.orderbook.base_time}</span>}
              </div>
              {quote?.orderbook && quote.orderbook.asks.length + quote.orderbook.bids.length > 0 ? (
                <>
                  <table className="list book">
                    <tbody>
                      {[...quote.orderbook.asks].reverse().map((lv, i) => (
                        <tr key={`a${lv.price}`}>
                          <td className="muted">매도{quote.orderbook!.asks.length - i}</td>
                          <td className="down" onClick={() => { setPrice(String(lv.price)); keepAlive(); }}>
                            {lv.price.toLocaleString()}
                          </td>
                          <td style={{ textAlign: "right" }}>{lv.qty.toLocaleString()}</td>
                        </tr>
                      ))}
                      {quote.orderbook.bids.map((lv, i) => (
                        <tr key={`b${lv.price}`}>
                          <td className="muted">매수{i + 1}</td>
                          <td className="up" onClick={() => { setPrice(String(lv.price)); keepAlive(); }}>
                            {lv.price.toLocaleString()}
                          </td>
                          <td style={{ textAlign: "right" }}>{lv.qty.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="muted">
                    총 매도 {quote.orderbook.total_ask_qty.toLocaleString()} / 매수{" "}
                    {quote.orderbook.total_bid_qty.toLocaleString()}
                  </div>
                </>
              ) : (
                <div className="muted">호가 정보 없음 (장외이거나 조회 실패)</div>
              )}
            </div>
            <div className="formrow">
              <input inputMode="numeric" placeholder="수량(주)" value={qty}
                     onChange={(e) => { setQty(e.target.value); keepAlive(); }} />
              <input inputMode="numeric" placeholder="가격(원)" value={price}
                     onChange={(e) => { setPrice(e.target.value); keepAlive(); }} />
            </div>
            {error && <div className="error">{error}</div>}
            <button className="primary" onClick={doPreview} disabled={busy || !qty || !price}>
              주문 확인
            </button>
          </>
        )}
      </div>
    </div>
  );
}
