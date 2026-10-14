// API 클라이언트 — 오류는 {error: {code, message, detail}}를 ApiError로 바꿔 던진다.
// 공유 파일: 화면별 호출 모음(Market·Stocks·Watchlist·Portfolios …)은 각 단계 담당이 맨 아래 자기 구역에 추가한다.
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(status, code, message, detail) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export async function request(method, path, { params, body, signal } = {}) {
  const url = new URL(BASE + path, location.origin);
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  }
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;            // 이어 입력해서 취소한 요청은 호출한 쪽이 무시한다
    throw new ApiError(0, "NETWORK_ERROR", "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error || {};
    throw new ApiError(res.status, e.code || "HTTP_ERROR", e.message || `요청이 실패했습니다 (${res.status})`, e.detail);
  }
  return data;
}

export const api = {
  get: (path, params) => request("GET", path, { params }),
  post: (path, body) => request("POST", path, { body }),
  put: (path, body) => request("PUT", path, { body }),
  patch: (path, body) => request("PATCH", path, { body }),
  del: (path, params) => request("DELETE", path, { params }),
};

// 화면에서 쓰는 호출 모음 ----------------------------------------------------------
// ── [S1-A] Market · Stocks ──
// group 은 경쟁 그룹 '이름'(예: "반도체"), q 는 이름·티커 검색어 — 원본 stocks.js 와 같은 방식
export const getStocks = ({ country, sort = "market_cap", order = "desc", group, q, limit = 100, offset = 0 } = {}) =>
  api.get("/stocks", { country, sort, order, group, q, limit, offset });

export const getStock = (market, ticker) => api.get(`/stocks/${market}/${ticker}`);

export const getCandles = (market, ticker, range = "1m") =>
  api.get(`/stocks/${market}/${ticker}/candles`, { range });

export const getPeerGroups = () => api.get("/peer-groups");
export const getIndices = () => api.get("/market/indices");
export const getFx = () => api.get("/market/fx");

// ── [S2-A] Watchlist · Portfolios ──
// TODO(연결): B의 /api/v1/watchlist (GET·POST·PATCH order·DELETE) — 연결 시 MOCK_WATCH=false 로 바꾸고 mockWatchlist·mock* 도우미 삭제
const MOCK_WATCH = true;

// 관심종목 -------------------------------------------------------------------------
export const getWatchlist = () => (MOCK_WATCH ? mockWatchlist.list() : api.get("/watchlist"));
export const addWatch = (market, ticker) =>
  MOCK_WATCH ? mockWatchlist.add(market, ticker) : api.post("/watchlist", { market, ticker });
export const removeWatch = (market, ticker) =>
  MOCK_WATCH ? mockWatchlist.remove(market, ticker) : api.del(`/watchlist/${market}/${ticker}`);
// items: [{market, ticker, sort_order}] — 바꿀 종목만 보내도 된다
export const reorderWatchlist = (items) =>
  MOCK_WATCH ? mockWatchlist.reorder(items) : api.patch("/watchlist/order", { items });

// 포트폴리오 -----------------------------------------------------------------------
// addPortfolioItem body: {market, ticker, mode: "quantity"|"amount"|"weight", value, memo?}
export const getPortfolios = () => api.get("/portfolios");
export const createPortfolio = (name, seed_krw) => api.post("/portfolios", { name, seed_krw });
export const updatePortfolio = (id, name, seed_krw) => api.put(`/portfolios/${id}`, { name, seed_krw });
export const deletePortfolio = (id) => api.del(`/portfolios/${id}`);
export const getPortfolioSummary = (id) => api.get(`/portfolios/${id}/summary`);
export const addPortfolioItem = (id, body) => api.post(`/portfolios/${id}/items`, body);
export const updatePortfolioItem = (id, itemId, body) => api.put(`/portfolios/${id}/items/${itemId}`, body);
export const deletePortfolioItem = (id, itemId) => api.del(`/portfolios/${id}/items/${itemId}`);

// ---- MOCK (docs/06 3-4 응답 모양). 종목 이름·가격은 진짜 /stocks 에서 가져오고,
// ---- 담은 목록만 브라우저(localStorage)에 저장한다. 에러(404·409)도 진짜와 같은 코드로 낸다.
const mockErr = (status, code, message, detail = {}) => new ApiError(status, code, message, detail);

function mockLoad(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function mockSave(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장소를 못 쓰면 이번 화면에서만 유지 */ }
}

const WATCH_KEY = "s2mock:watchlist";
const mockWatchlist = {
  async _card(row) {
    const s = await getStock(row.market, row.ticker);
    return {
      sort_order: row.sort_order, added_at: row.added_at, stock_id: s.stock_id, market: s.market,
      country: s.country, currency: s.currency, ticker: s.ticker, name: s.name, as_of: s.as_of,
      close: s.close, change: s.change, change_rate: s.change_rate,
    };
  },
  async list() {
    const rows = mockLoad(WATCH_KEY, []).sort((a, b) => a.sort_order - b.sort_order);
    const items = await Promise.all(rows.map((r) => this._card(r)));
    return { user_id: 1, count: items.length, items };
  },
  async add(market, ticker) {
    await getStock(market, ticker);                                   // 없는 종목이면 진짜 404 가 그대로 나간다
    const rows = mockLoad(WATCH_KEY, []);
    if (rows.some((r) => r.market === market && r.ticker === ticker)) {
      throw mockErr(409, "DUPLICATE_WATCHLIST", "이미 관심종목에 있습니다", { market, ticker });
    }
    const row = { market, ticker, added_at: new Date().toISOString(), sort_order: Math.max(0, ...rows.map((r) => r.sort_order)) + 1 };
    mockSave(WATCH_KEY, [...rows, row]);
    return this._card(row);
  },
  async remove(market, ticker) {
    const rows = mockLoad(WATCH_KEY, []);
    if (!rows.some((r) => r.market === market && r.ticker === ticker)) {
      throw mockErr(404, "WATCHLIST_ITEM_NOT_FOUND", "관심종목이 아닙니다", { market, ticker });
    }
    mockSave(WATCH_KEY, rows.filter((r) => !(r.market === market && r.ticker === ticker)));
    return null;
  },
  async reorder(items) {
    const rows = mockLoad(WATCH_KEY, []);
    for (const it of items) {
      const row = rows.find((r) => r.market === it.market && r.ticker === it.ticker);
      if (!row) throw mockErr(404, "WATCHLIST_ITEM_NOT_FOUND", "관심종목이 아닙니다", { market: it.market, ticker: it.ticker });
      row.sort_order = it.sort_order;
    }
    mockSave(WATCH_KEY, rows);
    return this.list();
  },
};

// ── [S3-A] 갱신 상태 ──

// ── [S4-A] 매력도 프리셋 · 분석 ──

// ── [S5] 홈 · 통계 · 검색 ──
