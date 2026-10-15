// 대시보드 홈: 주요 지수 5개 + USD/KRW 카드 (값·등락·스파크라인) + 내 관심종목 카드
import { getFx, getIndices, getWatchlist, reorderWatchlist } from "../api.js";
import { changeHtml, date, dateTime, esc, num, price, shortDate, stockUrl, usd } from "../format.js";
import { color, destroyCharts, sparkline } from "../components/charts.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";   // [S3-A] REFRESHED_EVENT
import { emptyState, h, load, segmented, skeleton, toast } from "../components/ui.js";

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

// ---------------------------------------------------------------- 내 관심종목 [S2-A]
let watchItems = [];

function watchCard(w, i) {
  const us = w.currency === "USD";
  const el = h(`<li class="wl-card">
      <a class="wl-card__link card--link" href="${stockUrl(w.market, w.ticker)}" aria-label="${esc(w.name)} 상세 보기">
        <div class="wl-card__head"><strong>${esc(w.name)}</strong>
          <span class="badge ${us ? "badge--us" : "badge--kr"}">${esc(w.market)}</span></div>
        <div class="subtle">${esc(w.ticker)} · ${shortDate(w.as_of)} 종가</div>
        <div class="wl-card__price num">${price(w.close, w.currency)}</div>
        <div class="wl-card__chg num">${changeHtml(w.change_rate, w.country)}</div>
      </a>
      <div class="wl-card__move">
        <button class="btn btn--sm" type="button" data-dir="-1" aria-label="${esc(w.name)} 위로" ${i === 0 ? "disabled" : ""}>▲</button>
        <button class="btn btn--sm" type="button" data-dir="1" aria-label="${esc(w.name)} 아래로" ${i === watchItems.length - 1 ? "disabled" : ""}>▼</button>
      </div>
    </li>`);
  el.querySelectorAll("[data-dir]").forEach((b) => b.addEventListener("click", () => moveWatch(i, Number(b.dataset.dir))));
  return el;
}

function renderWatch(items) {
  watchItems = items;
  $("#watch-count").textContent = `${items.length}개 종목`;
  const ul = h('<ul class="wl-grid" aria-label="내 관심종목"></ul>');
  ul.append(...items.map(watchCard));
  return ul;
}

// 이웃 카드와 자리를 바꾼다 — 화면은 먼저 바꾸고, 서버 저장이 실패하면 원래대로 되돌린다
async function moveWatch(i, dir) {
  const j = i + dir;
  const before = watchItems;
  const a = before[i], b = before[j];
  const next = [...before];
  next[i] = { ...b, sort_order: a.sort_order };
  next[j] = { ...a, sort_order: b.sort_order };
  $("#watchlist").replaceChildren(renderWatch(next));
  try {
    const res = await reorderWatchlist([
      { market: a.market, ticker: a.ticker, sort_order: b.sort_order },
      { market: b.market, ticker: b.ticker, sort_order: a.sort_order },
    ]);
    $("#watchlist").replaceChildren(renderWatch(res.items));
  } catch (e) {
    toast(e.message, "error");
    $("#watchlist").replaceChildren(renderWatch(before));
  }
}

function loadWatchlist() {
  return load($("#watchlist"), {
    skeleton: skeleton("card", 3),
    fetch: async () => (await getWatchlist()).items,
    render: renderWatch,
    empty: emptyState({ title: "관심종목이 없습니다", body: "주식 리스트에서 ★를 눌러 담아 보세요.",
      action: '<a class="btn btn--primary" href="/stocks">주식 리스트로</a>' }),
  });
}

loadWatchlist();

// ── [S3-A] 사이드바 새로고침이 끝나면 지수·환율·관심종목을 새 값으로 다시 불러온다 ──
document.addEventListener(REFRESHED_EVENT, () => { loadMarket(); loadWatchlist(); });
