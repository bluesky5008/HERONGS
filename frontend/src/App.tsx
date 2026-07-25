import { useCallback, useEffect, useState } from "react";
import { api, ApiError, Regime } from "./api";
import { Dashboard } from "./views/Dashboard";
import { StockView } from "./views/StockView";
import { PortfolioView } from "./views/PortfolioView";
import { PerformanceView } from "./views/PerformanceView";
import { SettingsView } from "./views/SettingsView";

type Page = "dashboard" | "stock" | "portfolio" | "performance" | "settings";

const NAV: { key: Page; label: string; ico: string }[] = [
  { key: "dashboard", label: "추천", ico: "📈" },
  { key: "stock", label: "종목", ico: "🔍" },
  { key: "portfolio", label: "잔고", ico: "💼" },
  { key: "performance", label: "성과", ico: "📊" },
  { key: "settings", label: "설정", ico: "⚙️" },
];

export function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [page, setPage] = useState<Page>("dashboard");
  const [regime, setRegime] = useState<Regime | null>(null);
  const [stockCode, setStockCode] = useState("");

  const refreshRegime = useCallback(() => {
    api.regime().then(setRegime).catch(() => undefined);
  }, []);

  useEffect(() => {
    // 세션 확인을 겸한 첫 호출 (§7 PIN 세션)
    api
      .regime()
      .then((r) => {
        setRegime(r);
        setAuthed(true);
      })
      .catch((e) => setAuthed(!(e instanceof ApiError && e.status === 401)));
  }, []);

  if (authed === null) return <div className="login">불러오는 중…</div>;
  if (!authed) return <Login onSuccess={() => { setAuthed(true); refreshRegime(); }} />;

  const openStock = (code: string) => {
    setStockCode(code);
    setPage("stock");
  };

  return (
    <>
      <header className="topbar">
        <h1>HERONGS</h1>
        {regime && <span className={`badge ${regime.label}`}>{regimeLabel(regime.label)}</span>}
      </header>
      <nav className="bottom">
        {NAV.map((n) => (
          <button key={n.key} className={page === n.key ? "active" : ""} onClick={() => setPage(n.key)}>
            <span className="ico">{n.ico}</span>
            {n.label}
          </button>
        ))}
      </nav>
      <main>
        {page === "dashboard" && <Dashboard onSelect={openStock} onScanned={refreshRegime} />}
        {page === "stock" && <StockView code={stockCode} onCode={setStockCode} />}
        {page === "portfolio" && <PortfolioView onSelect={openStock} />}
        {page === "performance" && <PerformanceView />}
        {page === "settings" && <SettingsView />}
      </main>
    </>
  );
}

export function regimeLabel(label: string): string {
  return { bull: "상승장", bear: "하락장", sideways: "횡보장" }[label] ?? label;
}

function Login({ onSuccess }: { onSuccess: () => void }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const submit = async () => {
    try {
      await api.login(pin);
      onSuccess();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "로그인 실패");
    }
  };
  return (
    <div className="login">
      <h1>HERONGS</h1>
      <input
        type="password"
        inputMode="numeric"
        placeholder="PIN"
        value={pin}
        onChange={(e) => setPin(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      {error && <div className="error">{error}</div>}
      <button className="primary" style={{ maxWidth: 240 }} onClick={submit}>
        로그인
      </button>
    </div>
  );
}
