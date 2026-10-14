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
// TODO(선행 머지 후 제거): MOCK_S2 와 아래 mock* 코드 전부 — B(/watchlist)·C(/portfolios)가 머지되면 false 로 바꾸고 지운다.
const MOCK_S2 = true;

// 관심종목 -------------------------------------------------------------------------
export const getWatchlist = () => (MOCK_S2 ? mockWatchlist.list() : api.get("/watchlist"));
export const addWatch = (market, ticker) =>
  MOCK_S2 ? mockWatchlist.add(market, ticker) : api.post("/watchlist", { market, ticker });
export const removeWatch = (market, ticker) =>
  MOCK_S2 ? mockWatchlist.remove(market, ticker) : api.del(`/watchlist/${market}/${ticker}`);
// items: [{market, ticker, sort_order}] — 바꿀 종목만 보내도 된다
export const reorderWatchlist = (items) =>
  MOCK_S2 ? mockWatchlist.reorder(items) : api.patch("/watchlist/order", { items });

// 포트폴리오 -----------------------------------------------------------------------
// addPortfolioItem body: {market, ticker, mode: "quantity"|"amount"|"weight", value, memo?}
export const getPortfolios = () => (MOCK_S2 ? mockPortfolio.list() : api.get("/portfolios"));
export const createPortfolio = (name, seed_krw) =>
  MOCK_S2 ? mockPortfolio.create(name, seed_krw) : api.post("/portfolios", { name, seed_krw });
export const updatePortfolio = (id, name, seed_krw) =>
  MOCK_S2 ? mockPortfolio.update(id, name, seed_krw) : api.put(`/portfolios/${id}`, { name, seed_krw });
export const deletePortfolio = (id) => (MOCK_S2 ? mockPortfolio.remove(id) : api.del(`/portfolios/${id}`));
export const getPortfolioSummary = (id) =>
  MOCK_S2 ? mockPortfolio.summary(id) : api.get(`/portfolios/${id}/summary`);
export const addPortfolioItem = (id, body) =>
  MOCK_S2 ? mockPortfolio.addItem(id, body) : api.post(`/portfolios/${id}/items`, body);
export const updatePortfolioItem = (id, itemId, body) =>
  MOCK_S2 ? mockPortfolio.updateItem(id, itemId, body) : api.put(`/portfolios/${id}/items/${itemId}`, body);
export const deletePortfolioItem = (id, itemId) =>
  MOCK_S2 ? mockPortfolio.removeItem(id, itemId) : api.del(`/portfolios/${id}/items/${itemId}`);

// ---- MOCK (docs/06 3-4·3-5 응답 모양). 종목 이름·가격·환율은 진짜 /stocks·/market/fx 에서 가져오고,
// ---- 담은 목록만 브라우저(localStorage)에 저장한다. 에러(409·422)도 진짜와 같은 코드로 낸다.
const r2 = (n) => Math.round(n * 100) / 100;
const mockErr = (status, code, message, detail = {}) => new ApiError(status, code, message, detail);

function mockLoad(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function mockSave(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장소를 못 쓰면 이번 화면에서만 유지 */ }
}

// 종목 한 건의 현재 시세 — USD 종목은 환율을 같이 돌려준다 (KRW 는 1)
async function mockQuote(market, ticker) {
  const s = await getStock(market, ticker);
  return { stock: s, price: s.close, fx: s.currency === "USD" ? s.fx_rate : 1, date: s.as_of };
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

const PF_KEY = "s2mock:portfolios";
const mockPortfolio = {
  _db: () => mockLoad(PF_KEY, { next_id: 1, next_item_id: 1, list: [] }),
  _find(db, id) {
    const p = db.list.find((x) => x.portfolio_id === Number(id));
    if (!p) throw mockErr(404, "PORTFOLIO_NOT_FOUND", "포트폴리오를 찾을 수 없습니다", { portfolio_id: Number(id) });
    return p;
  },
  _used: (p) => r2(p.items.reduce((a, i) => a + i.cost_krw, 0)),
  _out(p) {
    const used = this._used(p);
    return {
      portfolio_id: p.portfolio_id, user_id: 1, name: p.name, currency: "KRW", seed_krw: p.seed_krw,
      used_krw: used, remaining_krw: r2(p.seed_krw - used), item_count: p.items.length,
      created_at: p.created_at, updated_at: p.updated_at,
    };
  },
  // 수량/금액/비중 → 정수 수량 (1주 원화 원가 = 가격 × 환율)
  _quantity(mode, value, unit, seed) {
    if (mode === "quantity") return Math.floor(value);
    if (mode === "amount") return Math.floor(value / unit);
    if (mode === "weight") return Math.floor((seed * value) / 100 / unit);
    throw mockErr(422, "VALIDATION_ERROR", "mode 는 quantity·amount·weight 중 하나여야 합니다", { mode });
  },
  _itemOut(p, i) {
    return {
      item_id: i.item_id, portfolio_id: p.portfolio_id, stock_id: i.stock_id, market: i.market, ticker: i.ticker,
      name: i.name, currency: i.currency, quantity: i.quantity, ref_price: i.ref_price, ref_fx_rate: i.ref_fx_rate,
      ref_date: i.ref_date, cost_krw: i.cost_krw, memo: i.memo ?? null, created_at: i.created_at, updated_at: i.updated_at,
    };
  },
  // 담는(또는 수정하는) 순간의 가격·환율을 항목에 복사한다 — 서버의 '의도적 비정규화'와 같은 동작
  async _build(p, body, keep) {
    const q = await mockQuote(body.market, body.ticker);
    const unit = q.price * q.fx;
    const quantity = this._quantity(body.mode, Number(body.value), unit, p.seed_krw);
    if (quantity < 1) {
      throw mockErr(422, "QUANTITY_ZERO", "계산된 수량이 0주입니다. 금액이나 비중을 늘려 주세요", {
        min_amount_krw: Math.ceil(unit), min_weight_pct: r2((unit / p.seed_krw) * 100), unit_cost_krw: r2(unit),
      });
    }
    const cost = r2(quantity * unit);
    const used = r2(p.items.filter((i) => i !== keep).reduce((a, i) => a + i.cost_krw, 0));
    if (used + cost > p.seed_krw) {
      throw mockErr(409, "SEED_EXCEEDED", "담은 원가 합계가 시드를 넘습니다", {
        seed_krw: p.seed_krw, used_krw: used, remaining_krw: r2(p.seed_krw - used), requested_quantity: quantity,
        requested_cost_krw: cost, max_quantity: Math.floor((p.seed_krw - used) / unit), unit_cost_krw: r2(unit),
      });
    }
    const s = q.stock;
    return {
      stock_id: s.stock_id, market: s.market, country: s.country, ticker: s.ticker, name: s.name, currency: s.currency,
      groups: (s.groups || []).map((g) => g.name), quantity, ref_price: q.price, ref_fx_rate: q.fx, ref_date: q.date,
      cost_krw: cost, memo: body.memo ?? keep?.memo ?? null,
    };
  },

  async list() {
    const db = this._db();
    return db.list.map((p) => this._out(p));                          // 진짜 서버도 배열을 그대로 돌려준다
  },
  async create(name, seed_krw) {
    const db = this._db();
    if (db.list.some((p) => p.name === name)) throw mockErr(409, "DUPLICATE_PORTFOLIO", "같은 이름의 포트폴리오가 있습니다", { name });
    const now = new Date().toISOString();
    const p = { portfolio_id: db.next_id++, name, seed_krw: Number(seed_krw), items: [], created_at: now, updated_at: now };
    db.list.push(p);
    mockSave(PF_KEY, db);
    return this._out(p);
  },
  async update(id, name, seed_krw) {
    const db = this._db();
    const p = this._find(db, id);
    if (db.list.some((x) => x !== p && x.name === name)) throw mockErr(409, "DUPLICATE_PORTFOLIO", "같은 이름의 포트폴리오가 있습니다", { name });
    const used = this._used(p);
    if (Number(seed_krw) < used) {
      throw mockErr(409, "SEED_BELOW_USED", "시드를 현재 담은 원가 합계보다 작게 줄일 수 없습니다", { used_krw: used, requested_seed_krw: Number(seed_krw) });
    }
    Object.assign(p, { name, seed_krw: Number(seed_krw), updated_at: new Date().toISOString() });
    mockSave(PF_KEY, db);
    return this._out(p);
  },
  async remove(id) {
    const db = this._db();
    const p = this._find(db, id);
    db.list = db.list.filter((x) => x !== p);
    mockSave(PF_KEY, db);
    return null;
  },
  async addItem(id, body) {
    const db = this._db();
    const p = this._find(db, id);
    const dup = p.items.find((i) => i.market === body.market && i.ticker === body.ticker);
    if (dup) {
      throw mockErr(409, "DUPLICATE_ITEM", "이미 담은 종목입니다. 수량을 바꾸려면 수정(PUT)을 사용하세요", {
        item_id: dup.item_id, hint: `PUT /api/v1/portfolios/${p.portfolio_id}/items/${dup.item_id}`,
      });
    }
    const now = new Date().toISOString();
    const item = { item_id: db.next_item_id++, ...(await this._build(p, body)), created_at: now, updated_at: now };
    p.items.push(item);
    p.updated_at = now;
    mockSave(PF_KEY, db);
    return this._itemOut(p, item);
  },
  async updateItem(id, itemId, body) {
    const db = this._db();
    const p = this._find(db, id);
    const old = p.items.find((i) => i.item_id === Number(itemId));
    if (!old) throw mockErr(404, "PORTFOLIO_ITEM_NOT_FOUND", "담은 종목을 찾을 수 없습니다", { item_id: Number(itemId) });
    const now = new Date().toISOString();
    // 수정하면 기준가·환율도 현재값으로 다시 복사된다
    Object.assign(old, await this._build(p, { ...body, market: old.market, ticker: old.ticker }, old), { updated_at: now });
    p.updated_at = now;
    mockSave(PF_KEY, db);
    return this._itemOut(p, old);
  },
  async removeItem(id, itemId) {
    const db = this._db();
    const p = this._find(db, id);
    if (!p.items.some((i) => i.item_id === Number(itemId))) {
      throw mockErr(404, "PORTFOLIO_ITEM_NOT_FOUND", "담은 종목을 찾을 수 없습니다", { item_id: Number(itemId) });
    }
    p.items = p.items.filter((i) => i.item_id !== Number(itemId));
    mockSave(PF_KEY, db);
    return null;
  },
  // 현재가·현재 환율로 평가 — 손익 = 가격 효과 + 환율 효과 (합이 정확히 총 손익)
  async summary(id) {
    const p = this._find(this._db(), id);
    const fx = await getFx();
    const used = this._used(p);
    const items = await Promise.all(p.items.map(async (i) => {
      const q = await mockQuote(i.market, i.ticker);
      const value = q.price * q.fx * i.quantity;
      return {
        item_id: i.item_id, stock_id: i.stock_id, market: i.market, country: i.country, currency: i.currency,
        ticker: i.ticker, name: i.name, quantity: i.quantity, ref_price: i.ref_price, ref_fx_rate: i.ref_fx_rate,
        ref_date: i.ref_date, memo: i.memo ?? null, score: null, cost_krw: i.cost_krw,
        weight: used ? i.cost_krw / used : 0,
        current_price: q.price, price_date: q.date, current_fx_rate: q.fx, value_krw: Math.round(value),
        pnl_krw: r2(value - i.cost_krw), pnl_rate: i.cost_krw ? (value - i.cost_krw) / i.cost_krw : 0,
        local_return: q.price / i.ref_price - 1, fx_return: q.fx / i.ref_fx_rate - 1,
        price_effect_krw: r2((q.price - i.ref_price) * i.quantity * i.ref_fx_rate),
        fx_effect_krw: r2(q.price * i.quantity * (q.fx - i.ref_fx_rate)), groups: i.groups || [],
      };
    }));
    const sum = (k) => r2(items.reduce((a, i) => a + i[k], 0));
    const weights = (keyOf) => {
      const m = new Map();
      items.forEach((i) => keyOf(i).forEach((k) => m.set(k, (m.get(k) || 0) + i.cost_krw)));
      return [...m].map(([k, c]) => ({ cost_krw: r2(c), weight: used ? c / used : 0, k }));
    };
    const total = items.reduce((a, i) => a + i.value_krw, 0);
    return {
      portfolio_id: p.portfolio_id, name: p.name, currency: "KRW", seed_krw: p.seed_krw, used_krw: used,
      remaining_krw: r2(p.seed_krw - used), usage_rate: p.seed_krw ? used / p.seed_krw : 0, items,
      market_weights: weights((i) => [i.country]).map(({ k, ...w }) => ({ ...w, country: k })),
      group_weights: weights((i) => i.groups).map(({ k, ...w }) => ({ ...w, group: k })),
      weighted_score: null, total_value_krw: total, total_pnl_krw: r2(total - used),
      total_pnl_rate: used ? (total - used) / used : 0, price_effect_krw: sum("price_effect_krw"),
      fx_effect_krw: sum("fx_effect_krw"), fx_rate: fx.usd_krw, fx_rate_at: fx.rate_at, fx_stale: fx.fx_stale,
      as_of: items.map((i) => i.price_date).sort().pop() ?? null, disclaimer: "모의 계산이며 투자 권유가 아닙니다.",
    };
  },
};

// ── [S3-A] 갱신 상태 ──

// ── [S4-A] 매력도 프리셋 · 분석 ──

// ── [S5] 홈 · 통계 · 검색 ──
