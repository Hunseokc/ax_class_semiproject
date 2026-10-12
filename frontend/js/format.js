// 숫자·날짜 포맷 유틸 — 모든 화면이 이 파일 하나만 쓴다.
// API의 비율은 소수(0.0123 = 1.23%), 금액은 원/달러 숫자다.

const nf = (digits = 0) => new Intl.NumberFormat("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
export const DASH = "–";

/** 천 단위 구분 숫자 */
export function num(v, digits = 0) {
  return isNum(v) ? nf(digits).format(v) : DASH;
}

/** 원화: 1조 이상 "1,590.2조원", 1억 이상 "3,120억원", 그 외 "70,000원" */
export function krw(v, { compact = false, unit = true } = {}) {
  if (!isNum(v)) return DASH;
  const u = unit ? "원" : "";
  const abs = Math.abs(v);
  if (compact && abs >= 1e12) return `${nf(abs >= 1e14 ? 0 : 1).format(v / 1e12)}조${u}`;
  if (compact && abs >= 1e8) return `${nf(0).format(v / 1e8)}억${u}`;
  if (compact && abs >= 1e4) return `${nf(0).format(v / 1e4)}만${u}`;
  return `${nf(0).format(Math.round(v))}${u}`;
}

/** 달러: "$332.89", compact면 "$4.86T" */
export function usd(v, { compact = false } = {}) {
  if (!isNum(v)) return DASH;
  if (compact) {
    const abs = Math.abs(v);
    for (const [d, s] of [[1e12, "T"], [1e9, "B"], [1e6, "M"]]) if (abs >= d) return `$${(v / d).toFixed(2)}${s}`;
  }
  return `$${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v)}`;
}

/** 종목 통화에 맞춘 가격 */
export function price(v, currency) {
  return currency === "USD" ? usd(v) : krw(v);
}

/** 비율 → 퍼센트. sign이면 +/− 부호 */
export function pct(v, { digits = 2, sign = false } = {}) {
  if (!isNum(v)) return DASH;
  const p = v * 100;
  const s = sign && p > 0 ? "+" : "";
  return `${s}${nf(digits).format(p)}%`;
}

/** 부호 붙은 금액 (원) */
export function signedKrw(v, opts = {}) {
  if (!isNum(v)) return DASH;
  return `${v > 0 ? "+" : ""}${krw(v, opts)}`;
}

/** 거래량: "1,289만주", "1.3억주" */
export function volume(v) {
  if (!isNum(v)) return DASH;
  if (v >= 1e8) return `${nf(1).format(v / 1e8)}억주`;
  if (v >= 1e4) return `${nf(0).format(v / 1e4)}만주`;
  return `${nf(0).format(v)}주`;
}

/** 등락 표시: 색(국내 상승 빨강·하락 파랑 / 미국 상승 초록·하락 빨강) + ▲▼ 기호 */
export function change(rate, country = "KR", { digits = 2 } = {}) {
  if (!isNum(rate)) return { text: DASH, cls: "chg chg--flat", label: "등락 정보 없음" };
  const c = country === "US" ? "us" : "kr";
  if (rate > 0) return { text: `▲ ${pct(rate, { digits })}`, cls: `chg chg--${c}-up`, label: `상승 ${pct(rate, { digits })}` };
  if (rate < 0) return { text: `▼ ${pct(Math.abs(rate), { digits })}`, cls: `chg chg--${c}-down`, label: `하락 ${pct(Math.abs(rate), { digits })}` };
  return { text: `– ${pct(0, { digits })}`, cls: "chg chg--flat", label: "보합" };
}

/** 등락 <span> HTML */
export function changeHtml(rate, country, opts) {
  const c = change(rate, country, opts);
  return `<span class="${c.cls}" aria-label="${c.label}">${c.text}</span>`;
}

/** 등락률 읽기용 문장: "1.09% 하락" / "0.22% 상승" / "보합" / "등락 정보 없음" (소수점 둘째 자리 기준) */
export function changeLabel(rate) {
  if (!isNum(rate)) return "등락 정보 없음";
  const r = Math.round(rate * 10000) / 10000;
  if (r === 0) return "보합";
  return `${pct(Math.abs(r))} ${r > 0 ? "상승" : "하락"}`;
}

/** 가격 (등락률): "273,000원 (▼1.09%)" — 국내·해외 같은 규칙(상승 빨강·하락 파랑·0% 회색, 값 없으면 (–)) */
export function formatPriceWithChange(value, currency, rate) {
  let cls = "flat", text = `(${DASH})`;
  if (isNum(rate)) {
    const r = Math.round(rate * 10000) / 10000;
    cls = r > 0 ? "up" : r < 0 ? "down" : "flat";
    text = `(${r > 0 ? "▲" : r < 0 ? "▼" : ""}${pct(Math.abs(r))})`;
  }
  return `<span class="pwc"><span class="pwc__price num">${price(value, currency)}</span><span class="pwc__chg pwc__chg--${cls} num">${text}</span></span>`;
}

const dtf = new Intl.DateTimeFormat("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
const df = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Seoul" });

/** "10. 06. 21:05" (서울 시간) */
export function dateTime(iso) {
  return iso ? dtf.format(new Date(iso)) : DASH;
}

/** "2026. 10. 06." — 날짜만 있는 값(YYYY-MM-DD)은 그대로 날짜로 취급 */
export function date(iso) {
  if (!iso) return DASH;
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.replaceAll("-", ". ") + "." : df.format(new Date(iso));
}

/** "10. 06." — 카드처럼 좁은 곳용 */
export function shortDate(iso) {
  if (!iso) return DASH;
  const [, m, d] = /^\d{4}-(\d{2})-(\d{2})/.exec(iso) || [];
  return m ? `${m}. ${d}.` : dateTime(iso).slice(0, 7);
}

/** "3분 전", "2시간 전" */
export function relative(iso) {
  if (!iso) return DASH;
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h}시간 전` : `${Math.round(h / 24)}일 전`;
}

/** 원형 아이콘용 이니셜: 한글은 첫 글자, 영문은 앞 두 글자 */
export function initials(name = "") {
  const n = name.trim();
  return /^[A-Za-z]/.test(n) ? n.slice(0, 2).toUpperCase() : n.slice(0, 1);
}

/** HTML 이스케이프 */
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function stockUrl(market, ticker) {
  return `/stocks/${encodeURIComponent(market)}/${encodeURIComponent(ticker)}`;
}
