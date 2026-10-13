// 대시보드 홈: 주요 지수 5개 + USD/KRW 카드 (값·등락·스파크라인) + 주요 종목(발표용 임시 고정 2종목)
import { getCandles, getFx, getIndices, getStock } from "../api.js";
import { changeHtml, date, dateTime, esc, krw, num, price, shortDate, stockUrl, usd, volume } from "../format.js";
import { color, dashedAxis, destroyCharts, draw, plainAxis, sparkline } from "../components/charts.js";
import { mountSidebar } from "../components/sidebar.js";
import { h, load, segmented, skeleton } from "../components/ui.js";

mountSidebar("home");
const $ = (sel) => document.querySelector(sel);
// 등락 색은 시장과 무관하게 상승 --up(빨강)·하락 --down(파랑)
const trendColor = (rate) => (!rate ? color("--text-2") : color(rate > 0 ? "--up" : "--down"));

// 화면에 보여줄 카드 (서버는 지수 10개를 주지만 이번 단계는 5개 + 환율)
const SHOWN = ["KOSPI", "KOSDAQ", "SPX", "IXIC", "DJI"];

// ---------------------------------------------------------------- 지수·환율
// 스파크라인 기간 — API는 1년치를 주고 화면에서 자른다(일봉 기준이라 '1일'은 없음). 기본 1개월
const SPARK_RANGES = [{ value: "1m", label: "1개월", months: 1 }, { value: "3m", label: "3개월", months: 3 }, { value: "1y", label: "1년", months: 12 }];
let sparkRange = "1m";
const sparkMeta = () => SPARK_RANGES.find((r) => r.value === sparkRange);

/** 기준일(YYYY-MM-DD)에서 선택 기간만큼 거슬러 올라간 점만 남긴다 */
function inRange(points, lastDate) {
  if (!lastDate) return points;
  const d = new Date(`${lastDate}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() - sparkMeta().months);
  const since = d.toISOString().slice(0, 10);
  return points.filter((p) => p.date >= since);
}

const localDay = (tz, at = new Date()) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(at);   // YYYY-MM-DD

/** 최신 데이터 날짜가 그 시장의 오늘이 아니면 배지. Stage 1 API에는 거래소 달력 판정(session_status)이 없어
 *  주말 여부로만 판단한다 (session_status는 이후 단계에서 API에 추가되면 다시 우선 사용) */
function sessionBadge(ix) {
  if (!ix.as_of) return "";
  const today = localDay(ix.country === "US" ? "America/New_York" : "Asia/Seoul");
  const dow = new Date(`${today}T00:00:00Z`).getUTCDay();
  const status = ix.as_of >= today ? "today" : dow === 0 || dow === 6 ? "holiday" : "previous_session";
  if (status === "today") return "";
  const [text, why] = status === "holiday"
    ? ["휴장", "오늘은 휴장일(거래소 달력 기준)이라 마지막 거래일 종가를 표시합니다"]
    : ["직전 거래일", "오늘 일봉이 아직 없어 직전 거래일 종가를 표시합니다(일봉 기준)"];
  return `<span class="badge badge--market" title="${why}">${text}</span>`;
}

function indexCard(ix) {
  const el = h(`<article class="metric-card" aria-label="${esc(ix.name)}">
      <div class="metric-card__label"><span title="${esc(ix.name)}">${esc(ix.name)}</span><span class="subtle">${esc(ix.country || "")}</span></div>
      <div class="metric-card__value num">${num(ix.close, 2)}</div>
      <div class="metric-card__spark"><canvas aria-hidden="true"></canvas></div>
      <div class="metric-card__meta"><span>${sparkMeta().label} 추이</span>${sessionBadge(ix)}</div>
      <div class="metric-card__foot">${changeHtml(ix.change_rate, ix.country)}<span class="subtle" title="기준일 ${date(ix.as_of)}">${shortDate(ix.as_of)}</span></div>
    </article>`);
  const closes = inRange(ix.sparkline || [], ix.as_of).map((p) => p.close);
  queueMicrotask(() => sparkline(el.querySelector("canvas"), closes, trendColor(ix.change_rate)));   // canvas가 붙은 뒤에 그린다
  return el;
}

function fxCard(fx) {
  const el = h(`<article class="metric-card" aria-label="원달러 환율">
      <div class="metric-card__label"><span>USD/KRW</span>${fx.fx_stale ? '<span class="badge badge--market" title="최신 환율을 가져오지 못해 마지막 값을 표시합니다">지연</span>' : '<span class="subtle">환율</span>'}</div>
      <div class="metric-card__value num">${num(fx.usd_krw, 2)}<span class="subtle">원</span></div>
      <div class="metric-card__spark"><canvas aria-hidden="true"></canvas></div>
      <div class="metric-card__meta"><span>${sparkMeta().label} 추이</span></div>
      <div class="metric-card__foot">${changeHtml(fx.change_rate, "KR")}<span class="subtle" title="환율 기준 시각 ${dateTime(fx.rate_at)}">${dateTime(fx.rate_at).slice(-5)}</span></div>
    </article>`);
  // 현재값이 SNAPSHOT(장중 시각)일 때만 끝에 덧붙인다. DAILY면 이미 history의 마지막 점이라 덧붙이면 꼬리가 평평해진다
  const history = inRange(fx.history || [], localDay("Asia/Seoul", new Date(fx.rate_at))).map((p) => p.usd_krw);
  const values = fx.granularity === "SNAPSHOT" ? [...history, fx.usd_krw] : history;
  queueMicrotask(() => sparkline(el.querySelector("canvas"), values, color("--lavender")));
  return el;
}

let market = { indices: null, fx: null, error: null };

function renderMarketRow() {
  const box = $("#market");
  destroyCharts(box);                                    // 카드를 갈아엎기 전에 이전 차트 정리
  const row = h('<div class="metric-row"></div>');
  const byCode = new Map((market.indices || []).map((i) => [i.code, i]));
  for (const code of SHOWN) if (byCode.has(code)) row.append(indexCard(byCode.get(code)));
  if (market.fx) row.append(fxCard(market.fx));
  if (market.error) {
    const card = h(`<div class="state state--error" role="alert"><p class="state__title">일부 지표를 불러오지 못했습니다</p>
      <p>${esc(market.error.message)}</p><button class="btn btn--sm" type="button">다시 시도</button></div>`);
    card.querySelector("button").addEventListener("click", loadMarket);
    row.append(card);
  }
  box.replaceChildren(row);
}

async function loadMarket() {
  const box = $("#market");
  destroyCharts(box);
  const sk = skeleton("card", SHOWN.length + 1);
  sk.className = "metric-row";
  box.replaceChildren(sk);
  // 둘 중 하나가 실패해도 나머지는 보여준다
  const [ix, fx] = await Promise.allSettled([getIndices(), getFx()]);
  market = {
    indices: ix.status === "fulfilled" ? ix.value.indices : null,
    fx: fx.status === "fulfilled" ? fx.value : null,
    error: ix.status === "rejected" ? ix.reason : fx.status === "rejected" ? fx.reason : null,
  };
  if (market.indices) $("#as-of").textContent = `일봉 기준 · 기준일 ${date(ix.value.as_of)}`;
  renderMarketRow();
}

$("#spark-range").append(segmented(SPARK_RANGES, sparkRange,
  (v) => { sparkRange = v; if (market.indices || market.fx) renderMarketRow(); }, { label: "스파크라인 기간" }));

loadMarket();

// ---------------------------------------------------------------- 주요 종목 [S1-D 발표용 임시]
// TODO(Stage 2 A): 관심종목 카드로 교체 — 원본 홈의 관심종목 자리. Stage 1에는 사용자·관심종목이 없어 2종목을 고정한다.
// 기존 조회 API(상세·캔들)만 쓰고 백엔드는 바꾸지 않는다.
const FEATURED = [{ market: "KOSPI", ticker: "005930" }, { market: "NASDAQ", ticker: "NVDA" }];
const FEATURED_RANGES = [{ value: "1m", label: "1개월" }, { value: "3m", label: "3개월" }, { value: "1y", label: "1년" }];
let featuredRange = "3m";

// 축 눈금은 짧게: 원화는 "25만원", 달러는 소수점 없이 "$200"
const axisMoney = (v, cur) => (cur === "USD" ? `$${num(v)}` : krw(v, { compact: true }));
// 부호는 통화 기호 앞에: "-$2.96", "+1,500원"
const signed = (v, cur) => (v === null || v === undefined ? "" : `${v > 0 ? "+" : v < 0 ? "-" : ""}${price(Math.abs(v), cur)}`);
/** 16진 색에 투명도를 붙인다 — 차트 아래 채우기용 */
const alpha = (hex, a) => (/^#[0-9a-f]{6}$/i.test(hex) ? `${hex}${Math.round(a * 255).toString(16).padStart(2, "0")}` : hex);

function featuredCard(s) {
  const us = s.currency === "USD";
  return h(`<a class="featured-card card--link" href="${stockUrl(s.market, s.ticker)}" aria-label="${esc(s.name)} 상세 보기">
      <div class="featured-card__head"><strong>${esc(s.name)}</strong>
        <span class="badge ${us ? "badge--us" : "badge--kr"}">${esc(s.market)}</span></div>
      <div class="subtle">${esc(s.ticker)} · ${shortDate(s.as_of)} 종가</div>
      <div class="featured-card__price num">${price(s.close, s.currency)}</div>
      <div class="featured-card__chg num">${changeHtml(s.change_rate, s.country)} <span class="subtle">${signed(s.change, s.currency)}</span></div>
      <div class="featured-card__sub subtle num">${us ? `≈ ${krw(s.close_krw)} · 환율 ${num(s.fx_rate, 2)}${s.fx_stale ? " (지연)" : ""}<br>` : ""}거래량 ${volume(s.volume)}</div>
      <span class="featured-card__more subtle">상세 보기 →</span>
    </a>`);
}

function featuredChart(s, candles) {
  const closes = candles.map((c) => c.close);
  const hi = Math.max(...closes), lo = Math.min(...closes);
  const label = FEATURED_RANGES.find((r) => r.value === featuredRange).label;
  const box = h(`<div class="featured-chart">
      <div class="featured-chart__head"><strong>${esc(s.name)} 종가 추이</strong>
        <span class="subtle num">${label} · 최고 ${price(hi, s.currency)} · 최저 ${price(lo, s.currency)}</span></div>
      <div class="featured-chart__plot"><canvas role="img" aria-label="${esc(s.name)} ${label} 종가 차트"></canvas></div>
    </div>`);
  const line = trendColor(closes.at(-1) - closes[0]);           // 기간 수익이면 상승색, 손실이면 하락색
  queueMicrotask(() => draw(box.querySelector("canvas"), {    // canvas가 화면에 붙은 뒤에 그린다
    type: "line",
    data: { labels: candles.map((c) => c.date), datasets: [{ label: "종가", data: closes, borderColor: line, borderWidth: 2,
      pointRadius: 0, tension: 0.2, fill: true, backgroundColor: alpha(line, 0.12) }] },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: {
        x: { ...plainAxis, ticks: { maxTicksLimit: 6, maxRotation: 0, callback(v) { return shortDate(this.getLabelForValue(v)); } } },
        y: { ...dashedAxis, position: "right", ticks: { maxTicksLimit: 5, callback: (v) => axisMoney(v, s.currency) } },
      },
      plugins: { tooltip: { callbacks: { title: (items) => date(items[0].label), label: (ctx) => `종가 ${price(ctx.raw, s.currency)}` } } },
    },
  }));
  return box;
}

function loadFeaturedRow(row, { market, ticker }) {
  destroyCharts(row);
  return load(row, {
    skeleton: h('<div class="featured-row"><div class="skeleton skeleton--card"></div><div class="skeleton skeleton--card"></div></div>'),
    fetch: () => Promise.all([getStock(market, ticker), getCandles(market, ticker, featuredRange)]),
    render: ([s, c]) => {
      const el = h('<div class="featured-row"></div>');
      el.append(featuredCard(s), c.candles.length ? featuredChart(s, c.candles)
        : h('<div class="featured-chart state" role="status"><p class="state__title">해당 기간의 시세가 없습니다</p></div>'));
      return el;
    },
  });
}

function loadFeatured() {
  const box = $("#featured");
  destroyCharts(box);
  box.replaceChildren(...FEATURED.map((f) => {
    const row = h("<div></div>");
    loadFeaturedRow(row, f);                                   // 한 종목이 실패해도 다른 종목은 보여준다
    return row;
  }));
}

$("#featured-count").textContent = `${FEATURED.length}개 종목`;
$("#featured-range").append(segmented(FEATURED_RANGES, featuredRange,
  (v) => { featuredRange = v; loadFeatured(); }, { label: "주요 종목 차트 기간" }));

loadFeatured();
