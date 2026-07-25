import { useState } from "react";
import { api, ApiError, Preview } from "../api";

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
            <button className="ghost" style={{ width: "100%", marginTop: 8 }} onClick={() => setPreview(null)}>
              돌아가기
            </button>
          </>
        ) : (
          <>
            <div className="formrow">
              <input inputMode="numeric" placeholder="수량(주)" value={qty} onChange={(e) => setQty(e.target.value)} />
              <input inputMode="numeric" placeholder="가격(원)" value={price} onChange={(e) => setPrice(e.target.value)} />
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
