// API 클라이언트 — 오류는 {error: {code, message, detail}}를 ApiError로 바꿔 던진다.
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(status, code, message, detail) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function request(method, path, { params, body } = {}) {
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
    });
  } catch {
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

async function getWithPreset(path, params) {
  try {
    return await request("GET", path, { params });
  } catch (e) {
    if (e.code !== "UNKNOWN_PRESET" || !params?.preset || params.preset === DEFAULT_PRESET) throw e;
    setPreset(DEFAULT_PRESET, { silent: true });     // 기억해 둔 프리셋이 없어졌으면 기본값으로 다시 요청
    return request("GET", path, { params: { ...params, preset: DEFAULT_PRESET } });
  }
}

export const api = {
  get: (path, params) => getWithPreset(path, params),
  post: (path, body) => request("POST", path, { body }),
  put: (path, body) => request("PUT", path, { body }),
  patch: (path, body) => request("PATCH", path, { body }),
  del: (path, params) => request("DELETE", path, { params }),
};

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

// 화면에서 쓰는 호출 모음
export const Market = {
  indices: () => api.get("/market/indices"),
  fx: () => api.get("/market/fx"),
  status: () => api.get("/market/refresh/status"),
  refresh: () => api.post("/market/refresh"),
};

export const Stocks = {
  list: (params) => api.get("/stocks", { limit: 100, preset: getPreset(), ...params }),
  groups: () => api.get("/peer-groups"),
  detail: (m, t) => api.get(`/stocks/${m}/${t}`),
  candles: (m, t, range) => api.get(`/stocks/${m}/${t}/candles`, { range }),
  analysis: (m, t, preset = getPreset()) => api.get(`/stocks/${m}/${t}/analysis`, { preset }),
  financials: (m, t) => api.get(`/stocks/${m}/${t}/financials`, { limit: 5 }),
  peers: (m, t) => api.get(`/stocks/${m}/${t}/peers`),
  peersChart: (m, t, range, groupId) => api.get(`/stocks/${m}/${t}/peers/chart`, { range, group_id: groupId }),
  disclosures: (m, t) => api.get(`/stocks/${m}/${t}/disclosures`, { limit: 5 }),
};

export const Watchlist = {
  list: () => api.get("/watchlist", { preset: getPreset() }),
  add: (market, ticker) => api.post("/watchlist", { market, ticker }),
  remove: (market, ticker) => api.del(`/watchlist/${market}/${ticker}`),
  update: (market, ticker, body) => api.put(`/watchlist/${market}/${ticker}`, body),
};

export const Stats = {
  monthly: (market, ticker, months = 12) => api.get("/statistics/monthly", { market, ticker, months }),
  ranking: (metric, country, limit = 5) => api.get("/statistics/ranking", { metric, country, limit }),
};

export const Scoring = {
  presets: () => api.get("/scoring/presets"),
};

export const Portfolios = {
  list: () => api.get("/portfolios"),
  create: (name, seed) => api.post("/portfolios", { name, seed_krw: seed }),
  update: (id, name, seed) => api.put(`/portfolios/${id}`, { name, seed_krw: seed }),
  remove: (id) => api.del(`/portfolios/${id}`),
  summary: (id) => api.get(`/portfolios/${id}/summary`),
  addItem: (id, body) => api.post(`/portfolios/${id}/items`, body),
  updateItem: (id, itemId, body) => api.put(`/portfolios/${id}/items/${itemId}`, body),
  removeItem: (id, itemId) => api.del(`/portfolios/${id}/items/${itemId}`),
  previewEqualWeight: (id, body) => api.post(`/portfolios/${id}/preview/equal-weight`, body),
};
