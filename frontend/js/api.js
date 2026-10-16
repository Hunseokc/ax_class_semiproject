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
export const getStocks = ({ country, sort = "market_cap", order = "desc", group, q, limit = 100, offset = 0, preset = getPreset() } = {}) =>   // [S4-A] preset
  getWithPreset("/stocks", { country, sort, order, group, q, limit, offset, preset });

export const getStock = (market, ticker) => api.get(`/stocks/${market}/${ticker}`);

export const getCandles = (market, ticker, range = "1m") =>
  api.get(`/stocks/${market}/${ticker}/candles`, { range });

export const getPeerGroups = () => api.get("/peer-groups");
export const getIndices = () => api.get("/market/indices");
export const getFx = () => api.get("/market/fx");

// ── [S2-A] Watchlist · Portfolios ──
// 관심종목 -------------------------------------------------------------------------
export const getWatchlist = (preset = getPreset()) => getWithPreset("/watchlist", { preset });   // [S4-A] preset
export const addWatch = (market, ticker) => api.post("/watchlist", { market, ticker });
export const removeWatch = (market, ticker) => api.del(`/watchlist/${market}/${ticker}`);
// items: [{market, ticker, sort_order}] — 바꿀 종목만 보내도 된다
export const reorderWatchlist = (items) => api.patch("/watchlist/order", { items });

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

// ── [S3-A] 갱신 상태 ──
// 재무(FY)·공시 — 상세 화면의 재무 추이·최근 공시
export const getFinancials = (market, ticker, limit = 5) =>
  api.get(`/stocks/${market}/${ticker}/financials`, { limit });
export const getDisclosures = (market, ticker, limit = 5) =>
  api.get(`/stocks/${market}/${ticker}/disclosures`, { limit });

// 사이드바의 마지막 갱신 시각·갱신 버튼
export const getRefreshStatus = () => api.get("/market/refresh/status");
export const postRefresh = () => api.post("/market/refresh");

// ── [S4-A] 매력도 프리셋 · 분석 ──
// 투자 성향(매력도 프리셋) — 대시보드·리스트·상세가 같은 값을 쓴다.
// 우선순위: URL ?preset= → 브라우저 저장값 → balanced. 바꾸면 저장값·URL을 갱신하고 preset-change 이벤트를 보낸다.
const PRESET_KEY = "scorePreset";
const LEGACY_PRESETS = { quality: "balanced" };      // 없어진 프리셋 → 대체값
export const DEFAULT_PRESET = "balanced";
export const PRESET_EVENT = "preset-change";

const normalizePreset = (code) => LEGACY_PRESETS[code] || code || DEFAULT_PRESET;
function storedPreset() {
  try { return localStorage.getItem(PRESET_KEY); } catch { return null; }
}

export function getPreset() {
  return normalizePreset(new URLSearchParams(location.search).get("preset") || storedPreset());
}

export function setPreset(code, { silent = false } = {}) {
  try { localStorage.setItem(PRESET_KEY, code); } catch { /* 저장 불가(사생활 보호 모드 등)면 URL로만 유지 */ }
  const url = new URL(location.href);
  url.searchParams.set("preset", code);
  history.replaceState(history.state, "", url);
  if (!silent) document.dispatchEvent(new CustomEvent(PRESET_EVENT, { detail: { preset: code } }));
}

// 링크로 받은 값은 저장해 두고, 옛 값(quality)은 대체값으로 바꿔 둔다
{
  const current = getPreset();
  if (storedPreset() !== current) {
    try { localStorage.setItem(PRESET_KEY, current); } catch { /* 저장 불가 */ }
  }
  const inUrl = new URLSearchParams(location.search).get("preset");
  if (inUrl && inUrl !== current) setPreset(current, { silent: true });
}

// 기억해 둔 프리셋이 서버에서 없어졌으면(422 UNKNOWN_PRESET) 기본값으로 한 번만 다시 요청한다
async function getWithPreset(path, params) {
  try {
    return await request("GET", path, { params });
  } catch (e) {
    if (e.code !== "UNKNOWN_PRESET" || !params?.preset || params.preset === DEFAULT_PRESET) throw e;
    setPreset(DEFAULT_PRESET, { silent: true });
    return request("GET", path, { params: { ...params, preset: DEFAULT_PRESET } });
  }
}

export const getAnalysis = (market, ticker, preset = getPreset()) =>
  getWithPreset(`/stocks/${market}/${ticker}/analysis`, { preset });
export const getPresets = () => api.get("/scoring/presets");
export const getPeers = (market, ticker) => api.get(`/stocks/${market}/${ticker}/peers`);
export const getPeersChart = (market, ticker, range, groupId) =>
  api.get(`/stocks/${market}/${ticker}/peers/chart`, { range, group_id: groupId });

// ── [S5] 홈 · 통계 · 검색 ──
