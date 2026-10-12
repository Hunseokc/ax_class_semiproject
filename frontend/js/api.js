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

// ── [S2-A] Watchlist · Portfolios ──

// ── [S3-A] 갱신 상태 ──

// ── [S4-A] 매력도 프리셋 · 분석 ──

// ── [S5] 홈 · 통계 · 검색 ──
