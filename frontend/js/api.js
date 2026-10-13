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
// MOCK=true 면 B의 API 없이 docs/06 3-1·3-2 예시와 같은 모양의 목 응답을 돌려준다.
// 통합 전에 MOCK 을 false 로 바꾸고 이 구역의 MOCK_*·mock* 코드를 지운다 (D가 확인).
const MOCK = true;
const MOCK_DELAY_MS = 300;                       // 로딩 스켈레톤이 보이도록 일부러 늦춘다

const wait = (data) => new Promise((resolve) => setTimeout(() => resolve(structuredClone(data)), MOCK_DELAY_MS));

export const getStocks = ({ country, sort = "market_cap", order = "desc", group, limit = 100, offset = 0 } = {}) =>
  MOCK ? mockStocks({ country, sort, order, group, limit, offset })
       : api.get("/stocks", { country, sort, order, group, limit, offset });

export const getStock = (market, ticker) =>
  MOCK ? mockStock(market, ticker) : api.get(`/stocks/${market}/${ticker}`);

export const getCandles = (market, ticker, range = "1m") =>
  MOCK ? mockCandles(market, ticker, range) : api.get(`/stocks/${market}/${ticker}/candles`, { range });

export const getPeerGroups = () => (MOCK ? wait(MOCK_GROUPS) : api.get("/peer-groups"));
export const getIndices = () => (MOCK ? wait(MOCK_INDICES) : api.get("/market/indices"));
export const getFx = () => (MOCK ? wait(MOCK_FX) : api.get("/market/fx"));

// ---- 목 데이터 (실제 응답에서 score·preset·is_watched 를 뺀 모양) -----------------------
const MOCK_GROUPS = { groups: [{ group_id: 1, name: "반도체", size: 2 }, { group_id: 2, name: "빅테크", size: 1 }] };
const MOCK_GROUP_OF = { "005930": [1], "000660": [1], AAPL: [2] };

const MOCK_STOCKS = [
  { stock_id: 1, market: "KOSPI", country: "KR", currency: "KRW", ticker: "005930", name: "삼성전자",
    name_en: "SAMSUNG ELECTRONICS CO,.LTD", as_of: "2026-10-06", close: 273000, prev_close: 276000, change: -3000,
    change_rate: -0.01087, volume: 12895120, market_cap: 1590187781376000, market_cap_krw: 1590187781376000,
    per: 41.18, pbr: 4.25, eps: 6605, bps: 63997, shares_outstanding: 5846278608 },
  { stock_id: 2, market: "KOSPI", country: "KR", currency: "KRW", ticker: "000660", name: "SK하이닉스",
    name_en: "SK hynix Inc.", as_of: "2026-10-06", close: 1784000, prev_close: 1842000, change: -58000,
    change_rate: -0.031488, volume: 2726173, market_cap: 1295162963145000, market_cap_krw: 1295162963145000,
    per: 22.4, pbr: 5.1, eps: 79643, bps: 349800, shares_outstanding: 726000000 },
  { stock_id: 3, market: "NASDAQ", country: "US", currency: "USD", ticker: "AAPL", name: "Apple",
    name_en: "Apple Inc.", as_of: "2026-10-05", close: 316.22, prev_close: 315.34, change: 0.88,
    change_rate: 0.002791, volume: 35477100, market_cap: 4650000000000, market_cap_krw: 6203000000000000,
    per: 36.7, pbr: 52.1, eps: 8.62, bps: 6.07, shares_outstanding: 14700000000 },
];

const MOCK_INDEX_BASE = [
  ["KOSPI", "KR", "KRW", 6625.93, 6803.9], ["KOSDAQ", "KR", "KRW", 1012.4, 1004.1],
  ["S&P 500", "US", "USD", 6840.2, 6811.5], ["NASDAQ", "US", "USD", 23250.7, 23102.3], ["DOW", "US", "USD", 47310.5, 47420.9],
];

// 날짜 n개를 기준일부터 거슬러 올라가며 만든다 (주말 제외 = 거래일 근사)
function mockDates(asOf, n) {
  const out = [];
  const d = new Date(asOf + "T00:00:00Z");
  while (out.length < n) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out.reverse();
}

// 끝값(last)으로 수렴하는 결정적 파형 — 새로고침해도 같은 모양이 나온다
function mockSeries(last, n, seed) {
  return Array.from({ length: n }, (_, i) => {
    const wave = Math.sin((i + seed) / 3) * 0.02 + Math.sin((i + seed) / 9) * 0.03;
    return last * (1 + wave * ((n - 1 - i) / n));
  });
}

const MOCK_INDICES = {
  as_of: "2026-10-09",
  indices: MOCK_INDEX_BASE.map(([code, country, currency, close, prev], k) => ({
    code, name: code, country, currency, as_of: "2026-10-08", close, prev_close: prev,
    change: +(close - prev).toFixed(2), change_rate: +((close - prev) / prev).toFixed(6),
    sparkline: mockDates("2026-10-08", 60).map((date, i) => ({ date, close: +mockSeries(close, 60, k)[i].toFixed(2) })),
    session_status: "previous_session",
  })),
};

const MOCK_FX = {
  pair: "USD/KRW", currency: "KRW", usd_krw: 1333.98, rate_at: "2026-10-12T13:18:24.886505+09:00",
  granularity: "SNAPSHOT", fx_stale: false, prev_close: 1342.99, change: -9.01, change_rate: -0.006709,
  history: mockDates("2026-10-12", 60).map((date, i) => ({ date, usd_krw: +mockSeries(1333.98, 60, 5)[i].toFixed(2) })),
  as_of: "2026-10-12T13:18:24.886505+09:00",
};

const notFound = (market, ticker) =>
  new ApiError(404, "STOCK_NOT_FOUND", `종목 ${market}/${ticker}을(를) 찾을 수 없습니다`, null);

function mockStocks({ country, sort, order, group, limit, offset }) {
  if (sort === "volume" && !country) {             // 실제 API와 같은 규칙: 전체 탭은 거래량 정렬 불가
    return Promise.reject(new ApiError(422, "VOLUME_SORT_REQUIRES_MARKET",
      "시장마다 거래량 단위가 달라 '전체'에서는 거래량 정렬을 할 수 없습니다", null));
  }
  const key = sort === "volume" ? "volume" : "market_cap_krw";
  let rows = MOCK_STOCKS.filter((s) => (!country || s.country === country)
    && (!group || (MOCK_GROUP_OF[s.ticker] || []).includes(Number(group))));
  rows = rows.sort((a, b) => (order === "asc" ? a[key] - b[key] : b[key] - a[key]));
  const items = rows.slice(offset, offset + limit).map((s, i) => ({
    rank: offset + i + 1, stock_id: s.stock_id, market: s.market, country: s.country, currency: s.currency,
    ticker: s.ticker, name: s.name, name_en: s.name_en, as_of: s.as_of, close: s.close, change: s.change,
    change_rate: s.change_rate, volume: s.volume, market_cap: s.market_cap, market_cap_krw: s.market_cap_krw,
  }));
  return wait({ total: rows.length, limit, offset, sort, order, fx_rate_at: "2026-10-06T12:16:55.504460Z", items });
}

function mockStock(market, ticker) {
  const s = MOCK_STOCKS.find((x) => x.market === market && x.ticker === ticker);
  if (!s) return Promise.reject(notFound(market, ticker));
  const groups = MOCK_GROUPS.groups.filter((g) => (MOCK_GROUP_OF[ticker] || []).includes(g.group_id))
    .map(({ group_id, name }) => ({ group_id, name }));
  return wait({ ...s, valuation_as_of: s.as_of, groups });
}

const MOCK_RANGE_DAYS = { "1m": 21, "3m": 63, "6m": 126, "1y": 252 };

function mockCandles(market, ticker, range) {
  const s = MOCK_STOCKS.find((x) => x.market === market && x.ticker === ticker);
  if (!s) return Promise.reject(notFound(market, ticker));
  const n = MOCK_RANGE_DAYS[range] || 21;
  const closes = mockSeries(s.close, n, 2);
  const candles = mockDates(s.as_of, n).map((date, i) => {
    const close = +closes[i].toFixed(2);
    return { date, open: +(close * 0.995).toFixed(2), high: +(close * 1.01).toFixed(2),
             low: +(close * 0.985).toFixed(2), close, volume: Math.round(s.volume * (0.8 + (i % 5) / 10)) };
  });
  return wait({ market, ticker, currency: s.currency, range, as_of: s.as_of, candles });
}

// ── [S2-A] Watchlist · Portfolios ──

// ── [S3-A] 갱신 상태 ──

// ── [S4-A] 매력도 프리셋 · 분석 ──

// ── [S5] 홈 · 통계 · 검색 ──
