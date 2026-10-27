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
  // [2차 로그인] 로그인했으면 access token을 싣는다. 만료(401 TOKEN_EXPIRED)면 refresh 후 한 번 다시 보낸다
  const authPath = ["/auth/refresh", "/auth/login", "/auth/signup", "/auth/google"].some((x) => path.startsWith(x));
  if (!authPath) await ensureAccess();
  const send = async () => {
    const headers = body ? { "Content-Type": "application/json" } : {};
    if (!authPath && auth.token) headers.Authorization = `Bearer ${auth.token}`;
    try {
      return await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined, signal });
    } catch (e) {
      if (e.name === "AbortError") throw e;            // 이어 입력해서 취소한 요청은 호출한 쪽이 무시한다
      throw new ApiError(0, "NETWORK_ERROR", "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
    }
  };
  const read = async (r) => (r.status === 204 ? null : r.json().catch(() => null));
  let res = await send();
  let data = await read(res);
  if (res.status === 401 && !authPath && auth.token && ["TOKEN_EXPIRED", "INVALID_TOKEN"].includes(data?.error?.code)) {
    await refreshAccess();                            // 실패하면 토큰을 지운다 → 로그인 없이 다시 보낸다
    res = await send();
    data = await read(res);
  }
  if (res.status === 204) return null;
  if (!res.ok) {
    const e = data?.error || {};
    throw new ApiError(res.status, e.code || "HTTP_ERROR", e.message || `요청이 실패했습니다 (${res.status})`, e.detail);
  }
  return data;
}

// ── 2차 로그인: access token 보관 ──
// access token(15분)은 이 탭의 sessionStorage에만 둔다(화면을 옮겨도 다시 받지 않게). refresh token은 httpOnly 쿠키라 JS가 못 본다.
// "로그인한 적 있음" 표시(localStorage)가 있을 때만 새 탭에서 refresh를 시도한다 → 로그인하지 않은 사람은 refresh 호출이 없다.
const AT_KEY = "stockmind:at";
const HINT_KEY = "stockmind:logged-in";
const auth = { token: null, exp: 0, pending: null };
try {
  const saved = JSON.parse(sessionStorage.getItem(AT_KEY));
  if (saved?.token) Object.assign(auth, { token: saved.token, exp: saved.exp });
} catch { /* 저장 불가면 탭마다 refresh */ }

function setAccess(t) {
  auth.token = t?.access_token ?? null;
  auth.exp = t ? Date.now() + t.expires_in * 1000 : 0;
  try {
    if (auth.token) {
      sessionStorage.setItem(AT_KEY, JSON.stringify({ token: auth.token, exp: auth.exp }));
      localStorage.setItem(HINT_KEY, "1");
    } else {
      sessionStorage.removeItem(AT_KEY);
      localStorage.removeItem(HINT_KEY);
    }
  } catch { /* 저장 불가면 이번 화면에서만 유지 */ }
  return t;
}

const loggedInHint = () => { try { return localStorage.getItem(HINT_KEY) === "1"; } catch { return false; } };

/** refresh token으로 access token을 다시 받는다(동시에 여러 번 불러도 한 번만). 다른 탭과 겹치면(REFRESH_RETRY) 잠시 뒤 한 번 더. */
async function refreshAccess() {
  if (!auth.pending) {
    auth.pending = (async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        const res = await fetch(BASE + "/auth/refresh", { method: "POST" }).catch(() => null);
        const data = res ? await res.json().catch(() => null) : null;
        if (res?.ok) return setAccess(data);
        if (data?.error?.code !== "REFRESH_RETRY") break;
        await new Promise((r) => setTimeout(r, 300));
      }
      return setAccess(null);
    })().finally(() => { auth.pending = null; });
  }
  return auth.pending;
}

/** 요청 전에: 토큰이 곧(30초 안) 만료되거나, 새 탭이라 없는데 로그인한 적이 있으면 먼저 refresh */
async function ensureAccess() {
  if (auth.pending) return auth.pending;
  if (auth.token ? auth.exp - Date.now() < 30_000 : loggedInHint()) return refreshAccess();
  return null;
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
export const getStocks = ({ country, sort = "market_cap", order = "desc", group, sector, q, limit = 100, offset = 0, preset = getPreset() } = {}) =>   // [S4-A] preset
  getWithPreset("/stocks", { country, sort, order, group, sector, q, limit, offset, preset });

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
  if (!silent) savePref("preset");   // [2차 로그인] 사용자가 바꾼 값만 계정에도 저장
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

// ── [S5-A] 메모 · 월별 · 순위 · 균등 배분 ──
// 보낸 필드만 바뀌고, null 을 보내면 그 값이 지워진다(memo·target_price)
export const putWatchlist = (market, ticker, body) => api.put(`/watchlist/${market}/${ticker}`, body);
export const getMonthly = (market, ticker, months = 12) => api.get("/statistics/monthly", { market, ticker, months });
export const getRanking = (metric, country, limit = 5) => api.get("/statistics/ranking", { metric, country, limit });
// 저장하지 않는 계산 전용 — 담기는 기존 addPortfolioItem 으로 한다
export const previewEqualWeight = (id, body) => api.post(`/portfolios/${id}/preview/equal-weight`, body);

// ── [S6-A] 홈 위젯 · 상단 검색 ──
// 이어 입력하면 앞 요청을 취소해야 해서 signal 을 넘길 수 있는 request 를 직접 쓴다
export const searchStocks = (q, signal) => request("GET", "/stocks/search", { params: { q, limit: 8 }, signal });
// 시장 주목 종목 — kind: volume_surge(거래량 급증) · attractiveness(매력도 순위)
export const getHomeRanking = (kind, country, limit = 5, family = "general") =>
  api.get("/home/ranking", { kind, country, limit, preset: getPreset(), ...(kind === "attractiveness" ? { family } : {}) });
export const getSectors = (country) => api.get("/home/sectors", { country });
export const getSentiment = (country) => api.get("/home/sentiment", { country });

// ── 2차 로그인 ──
// getMe → {logged_in, user_id, nickname, email, has_password, has_google}. 로그인·가입·Google은 받은 access token을 보관한다
export const getAuthConfig = () => api.get("/auth/config");
export const getMe = () => api.get("/auth/me");
export const isLoggedIn = () => Boolean(auth.token) || loggedInHint();
export const signup = async (email, password, nickname) => setAccess(await api.post("/auth/signup", { email, password, nickname })).user;
export const login = async (email, password) => setAccess(await api.post("/auth/login", { email, password })).user;
export const googleLogin = async (credential) => setAccess(await api.post("/auth/google", { credential })).user;
export const logout = async () => { try { await api.post("/auth/logout"); } finally { setAccess(null); } };
export const logoutAll = async () => { await api.post("/auth/logout-all"); setAccess(null); };
export const changePassword = (current_password, new_password) => api.put("/auth/password", { current_password, new_password });
export const withdraw = async (password) => { await request("DELETE", "/auth/me", { body: { password } }); setAccess(null); };

// 사용자별 설정 — 화면은 지금처럼 localStorage를 읽고 쓰고, 로그인했으면 계정에도 저장한다(다른 기기에서 이어짐).
// 서버 칸 → localStorage 키·형식 (app/services/auth.py PREF_KEYS와 같은 목록)
const PREF_STORAGE = {
  theme: ["stockmind:theme", "str"], preset: ["scorePreset", "str"], metrics: ["marketMetrics", "json"],
  watch_view: ["watchViewHome", "str"], home_portfolio: ["homePortfolio", "num"],
};
const PREFS_SYNCED = "stockmind:prefs-synced";
const readPref = (name) => {
  const [key, kind] = PREF_STORAGE[name];
  try {
    const v = localStorage.getItem(key);
    if (v === null) return null;
    return kind === "json" ? JSON.parse(v) : kind === "num" ? Number(v) || null : v;
  } catch { return null; }
};
let prefTimer = null;
const dirtyPrefs = new Set();

/** localStorage에 저장한 설정 하나를 계정에도 저장한다(로그인했을 때만, 0.5초 모아서). */
export function savePref(name) {
  if (!PREF_STORAGE[name] || !isLoggedIn()) return;
  dirtyPrefs.add(name);
  clearTimeout(prefTimer);
  prefTimer = setTimeout(() => {
    const body = Object.fromEntries([...dirtyPrefs].map((n) => [n, readPref(n)]));
    dirtyPrefs.clear();
    api.put("/auth/me/preferences", body).catch(() => { /* 저장 실패해도 이 브라우저 값은 그대로 */ });
  }, 500);
}

/** 계정 설정을 localStorage로 가져온다(탭마다 한 번, force면 바로). 바뀐 게 있으면 true. */
export async function loadPrefs({ force = false } = {}) {
  try { if (!force && sessionStorage.getItem(PREFS_SYNCED)) return false; } catch { /* 계속 */ }
  const prefs = await api.get("/auth/me/preferences");
  let changed = false;
  for (const [name, [key, kind]] of Object.entries(PREF_STORAGE)) {
    const v = prefs[name];
    if (v === null || v === undefined) continue;
    const raw = kind === "json" ? JSON.stringify(v) : String(v);
    try {
      if (localStorage.getItem(key) !== raw) { localStorage.setItem(key, raw); changed = true; }
    } catch { /* 저장 불가 */ }
  }
  try { sessionStorage.setItem(PREFS_SYNCED, "1"); } catch { /* 저장 불가 */ }
  return changed;
}
