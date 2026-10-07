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
    if (e.code !== "UNKNOWN_PRESET" || !params?.preset || params.preset === "balanced") throw e;
    scorePreset.set("balanced");                     // 기억해 둔 프리셋이 없어졌으면 기본값으로 다시 요청
    return request("GET", path, { params: { ...params, preset: "balanced" } });
  }
}

export const api = {
  get: (path, params) => getWithPreset(path, params),
  post: (path, body) => request("POST", path, { body }),
  put: (path, body) => request("PUT", path, { body }),
  patch: (path, body) => request("PATCH", path, { body }),
  del: (path, params) => request("DELETE", path, { params }),
};

// 매력도 프리셋 선택 — 리스트·홈 카드·상세가 같은 프리셋을 쓰도록 브라우저에 기억 (서버 기본값: balanced)
const PRESET_KEY = "scorePreset";
export const scorePreset = {
  get() {
    try { return localStorage.getItem(PRESET_KEY) || "balanced"; } catch { return "balanced"; }
  },
  set(code) {
    try { localStorage.setItem(PRESET_KEY, code); } catch { /* 저장 불가(사생활 보호 모드 등)면 이번 화면에서만 적용 */ }
  },
};

// 화면에서 쓰는 호출 모음
export const Market = {
  indices: () => api.get("/market/indices"),
  fx: () => api.get("/market/fx"),
  status: () => api.get("/market/refresh/status"),
  refresh: () => api.post("/market/refresh"),
};

export const Stocks = {
  list: (params) => api.get("/stocks", { limit: 100, preset: scorePreset.get(), ...params }),
  groups: () => api.get("/peer-groups"),
  detail: (m, t) => api.get(`/stocks/${m}/${t}`),
  candles: (m, t, range) => api.get(`/stocks/${m}/${t}/candles`, { range }),
  analysis: (m, t, preset = scorePreset.get()) => api.get(`/stocks/${m}/${t}/analysis`, { preset }),
  financials: (m, t) => api.get(`/stocks/${m}/${t}/financials`, { limit: 5 }),
  peers: (m, t) => api.get(`/stocks/${m}/${t}/peers`),
  peersChart: (m, t, range, groupId) => api.get(`/stocks/${m}/${t}/peers/chart`, { range, group_id: groupId }),
  disclosures: (m, t) => api.get(`/stocks/${m}/${t}/disclosures`, { limit: 5 }),
};

export const Watchlist = {
  list: () => api.get("/watchlist", { preset: scorePreset.get() }),
  add: (market, ticker) => api.post("/watchlist", { market, ticker }),
  remove: (market, ticker) => api.del(`/watchlist/${market}/${ticker}`),
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
};
