// 백엔드 REST API 클라이언트 (설계 §4.2)

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* JSON 아님 */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json();
}

export const api = {
  login: (pin: string) =>
    request<{ ok: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ pin }),
    }),
  recommendations: (profile: string) =>
    request<{ profile: string; ts: string | null; items: RecItem[] }>(
      `/api/recommendations?profile=${profile}`,
    ),
  runScan: () => request("/api/scan", { method: "POST" }),
  regime: () => request<Regime>("/api/regime"),
  analysis: (code: string) => request<OpinionItem[]>(`/api/stocks/${code}/analysis`),
  prices: (code: string) => request<Candle[]>(`/api/stocks/${code}/prices`),
  portfolio: () => request<Portfolio>("/api/portfolio"),
  performance: () => request<Performance>("/api/performance"),
  openOrders: () => request<OpenOrder[]>("/api/orders/open"),
  previewOrder: (body: {
    side: string;
    code: string;
    qty: number;
    price: number;
    profile?: string;
  }) => request<Preview>("/api/orders/preview", { method: "POST", body: JSON.stringify(body) }),
  confirmOrder: (preview_id: string) =>
    request<{ ord_no: string; status: string }>("/api/orders/confirm", {
      method: "POST",
      body: JSON.stringify({ preview_id }),
    }),
  modifyOrder: (ordNo: string, code: string, qty: number, price: number) =>
    request<{ ord_no: string }>(`/api/orders/${ordNo}`, {
      method: "PUT",
      body: JSON.stringify({ code, qty, price }),
    }),
  cancelOrder: (ordNo: string, code: string) =>
    request(`/api/orders/${ordNo}?code=${code}`, { method: "DELETE" }),
  conditions: (refresh = false) =>
    request<Condition[]>(`/api/conditions?refresh=${refresh}`),
  mapCondition: (seq: string, profile: string, enabled: boolean) =>
    request(`/api/conditions/${seq}`, {
      method: "PUT",
      body: JSON.stringify({ profile, enabled }),
    }),
  watchlist: () => request<WatchItem[]>("/api/watchlist"),
  addWatch: (code: string) =>
    request("/api/watchlist", { method: "POST", body: JSON.stringify({ code }) }),
  removeWatch: (code: string) => request(`/api/watchlist/${code}`, { method: "DELETE" }),
  settings: () => request<AppSettings>("/api/settings"),
};

export interface RecItem {
  rank: number;
  code: string;
  name: string;
  score: number;
  breakdown: Record<string, { weight: number; subscore: number; points: number; details: Record<string, unknown> }>;
  regime: string;
}
export interface Regime {
  label: string;
  date: string | null;
  metrics: Record<string, unknown>;
}
export interface OpinionItem {
  profile: string;
  code: string;
  name: string;
  stance: string;
  score: number;
  score_breakdown: RecItem["breakdown"];
  override: string | null;
  regime: string;
  holding?: { avg_price: number; qty: number; pnl_pct: number; stop_price: number; target_price: number };
}
export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
export interface Portfolio {
  total_purchase: number;
  total_eval: number;
  total_pnl: number;
  total_pnl_pct: number;
  est_assets: number;
  stocks: {
    code: string;
    name: string;
    qty: number;
    avg_price: number;
    cur_price: number;
    pnl: number;
    pnl_pct: number;
    opinions?: Record<string, string>;
  }[];
}
export interface Performance {
  report: Record<string, Record<string, { count: number; hit_rate: number; avg_return: number }>>;
  history: {
    id: number;
    ts: string;
    profile: string;
    code: string;
    score: number;
    rank: number;
    regime: string;
    returns: Record<string, number>;
  }[];
}
export interface OpenOrder {
  ord_no: string;
  code: string;
  name: string;
  status: string;
  side: string;
  qty: number;
  price: number;
  unfilled_qty: number;
}
export interface Preview {
  preview_id: string;
  side: string;
  code: string;
  qty: number;
  price: number;
  amount: number;
  weight_pct: number | null;
  suggested_stop: number;
  suggested_target: number;
  trading_mode: string;
}
export interface Condition {
  seq: string;
  name: string;
  profile: string;
  enabled: boolean;
}
export interface WatchItem {
  code: string;
  name: string;
  group: string;
}
export interface AppSettings {
  trading_mode: string;
  max_order_amount: number;
  daily_order_limit: number;
  overrides: Record<string, string>;
}
