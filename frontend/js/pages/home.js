// 대시보드 홈: 주요 지수 5개 + USD/KRW 카드 (값·등락·스파크라인) + 내 관심종목 카드
import { PRESET_EVENT, getFx, getIndices, getPreset, getRanking, getWatchlist, reorderWatchlist } from "../api.js";   // [S4-A] PRESET_EVENT·getPreset  [S5-A] getRanking
import { changeHtml, date, dateTime, esc, num, pct, price, shortDate, stockUrl, usd, volume } from "../format.js";   // [S5-A] pct·volume
import { color, destroyCharts, scoreGauge, sparkline } from "../components/charts.js";   // [S4-A] scoreGauge
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";   // [S3-A] REFRESHED_EVENT
import { emptyState, h, load, marketBadge, segmented, skeleton, toast } from "../components/ui.js";   // [S5-A] marketBadge
import { loadPresets, mountPresetMenu } from "../components/preset-menu.js";   // [S4-A]
import { FX_CODE, DEFAULT_METRICS, metricPicker, storedMetrics } from "../components/metric-picker.js";   // [S5-A]
import { openWatchNote } from "../components/watch-note.js";   // [S5-A]
import { icons } from "../components/icons.js";   // [S5-A]

mountSidebar("home");
const $ = (sel) => document.querySelector(sel);
// 등락 색은 시장과 무관하게 상승 --up(빨강)·하락 --down(파랑)
const trendColor = (rate) => (!rate ? color("--text-2") : color(rate > 0 ? "--up" : "--down"));

// [S5-A] 화면에 보여줄 카드는 사용자가 metric-picker로 고른다(저장값 → 없으면 기본 5개 지수 + 환율)

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

// 마지막 응답 — 표시 지표를 바꿀 때는 다시 요청하지 않고 이 값으로 다시 그린다
let market = { indices: null, fx: null, error: null };
let shown = [];   // [S5-A]

function renderMarketRow() {
  const box = $("#market");
  destroyCharts(box);                                    // 카드를 갈아엎기 전에 이전 차트 정리
  const row = h('<div class="metric-row"></div>');
  const byCode = new Map((market.indices || []).map((i) => [i.code, i]));
  for (const code of shown) {   // [S5-A] 고른 순서대로(환율 포함)
    if (code === FX_CODE) { if (market.fx) row.append(fxCard(market.fx)); }
    else if (byCode.has(code)) row.append(indexCard(byCode.get(code)));
  }
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
  const sk = skeleton("card", shown.length || DEFAULT_METRICS.length);
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
  mountPicker();   // [S5-A] 고를 수 있는 지표가 정해졌으니 선택 상자를 만든다
  renderMarketRow();
}

$("#spark-range").append(segmented(SPARK_RANGES, sparkRange,
  (v) => { sparkRange = v; if (market.indices || market.fx) renderMarketRow(); }, { label: "스파크라인 기간" }));

// ── [S5-A] 표시 지표 선택 ──
// index.html은 A의 담당 파일이 아니라서, 이 파일이 버튼과 상자 자리를 만들어 붙인다
const editBtn = h('<button id="market-edit" class="btn btn--sm" type="button" aria-expanded="false" aria-controls="market-picker" disabled>표시 지표</button>');
$("#spark-range").before(editBtn);
$("#market").before(h('<div id="market-picker-slot"></div>'));
editBtn.addEventListener("click", () => togglePicker(editBtn.getAttribute("aria-expanded") !== "true"));

const availableMetrics = () => [...(market.indices || []).map((i) => i.code), FX_CODE];

function metricGroups() {
  const by = (country) => market.indices.filter((i) => i.country === country).map((i) => ({ code: i.code, name: i.name }));
  return [{ label: "국내", items: by("KR") }, { label: "미국", items: by("US") },
    { label: "환율", items: [{ code: FX_CODE, name: "USD/KRW" }] }].filter((g) => g.items.length);
}

function togglePicker(open, { focus = true } = {}) {
  const panel = $("#market-picker");
  if (!panel) return;
  panel.hidden = !open;
  editBtn.setAttribute("aria-expanded", String(open));
  if (focus) (open ? panel.querySelector(".chip:not(:disabled)") : editBtn)?.focus();
}

function mountPicker() {
  const wasOpen = editBtn.getAttribute("aria-expanded") === "true";
  shown = storedMetrics(availableMetrics());
  // 지수 목록을 못 받으면 고를 수 없다(저장된 선택을 덮어쓰지 않도록 설정을 막음)
  if (!market.indices) {
    $("#market-picker-slot").replaceChildren();
    editBtn.disabled = true;
    editBtn.setAttribute("aria-expanded", "false");
    return;
  }
  $("#market-picker-slot").replaceChildren(metricPicker({
    id: "market-picker", groups: metricGroups(), selected: shown,
    onChange: (codes) => { shown = codes; renderMarketRow(); },
    onClose: () => togglePicker(false),
  }));
  editBtn.disabled = false;
  togglePicker(wasOpen, { focus: false });
}

loadMarket();

// ---------------------------------------------------------------- 내 관심종목 [S2-A]
let watchItems = [];

// [S5-A] 목표가 줄 — 괴리율(target_gap)은 서버가 계산한 값을 그대로 쓴다
const watchTarget = (w) => (w.target_price != null
  ? `목표 ${price(w.target_price, w.currency)} (${w.target_gap != null ? pct(w.target_gap, { sign: true, digits: 1 }) : "–"})` : "");

function watchCard(w, i) {
  const us = w.currency === "USD";
  const target = watchTarget(w);   // [S5-A]
  const el = h(`<li class="wl-card">
      <a class="wl-card__link card--link" href="${stockUrl(w.market, w.ticker)}?preset=${encodeURIComponent(getPreset())}" aria-label="${esc(w.name)} 상세 보기">
        <div class="wl-card__gauge">${scoreGauge(w.score)}</div>
        <div class="wl-card__head"><strong>${esc(w.name)}</strong>
          <span class="badge ${us ? "badge--us" : "badge--kr"}">${esc(w.market)}</span></div>
        <div class="subtle">${esc(w.ticker)} · ${shortDate(w.as_of)} 종가</div>
        <div class="wl-card__price num">${price(w.close, w.currency)}</div>
        <div class="wl-card__chg num">${changeHtml(w.change_rate, w.country)}</div>
        ${target ? `<div class="subtle num">${esc(target)}</div>` : ""}
        ${w.memo ? `<div class="subtle" title="${esc(w.memo)}">${esc(w.memo)}</div>` : ""}
      </a>
      <div class="wl-card__move">
        <button class="btn btn--sm" type="button" data-edit aria-label="${esc(w.name)} 메모·목표가 편집" title="메모·목표가">${icons.edit}</button>
        <button class="btn btn--sm" type="button" data-dir="-1" aria-label="${esc(w.name)} 위로" ${i === 0 ? "disabled" : ""}>▲</button>
        <button class="btn btn--sm" type="button" data-dir="1" aria-label="${esc(w.name)} 아래로" ${i === watchItems.length - 1 ? "disabled" : ""}>▼</button>
      </div>
    </li>`);
  el.querySelector("[data-edit]").addEventListener("click", () => openWatchNote(w, () => loadWatchlist()));   // [S5-A]
  el.querySelectorAll("[data-dir]").forEach((b) => b.addEventListener("click", () => moveWatch(i, Number(b.dataset.dir))));
  return el;
}

function renderWatch(items) {
  watchItems = items;
  watchCount = items.length;   // [S4-A]
  paintWatchCount();
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
    const scoreOf = new Map(before.map((x) => [`${x.market}/${x.ticker}`, x.score]));   // [S4-A] 순서 응답에 점수가 없어도 유지
    $("#watchlist").replaceChildren(renderWatch(res.items.map((x) => ({ ...x, score: x.score ?? scoreOf.get(`${x.market}/${x.ticker}`) }))));
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
document.addEventListener(REFRESHED_EVENT, () => { loadMarket(); loadWatchlist(); loadRanking(); });   // [S5-A] loadRanking

// ── [S4-A] 투자 성향: 관심종목 카드의 매력도 게이지가 따르는 값 ──
// index.html은 A의 담당 파일 목록에 없어서, 이 파일이 성향 메뉴 자리를 '내 관심종목' 제목줄에 만들어 붙인다
let watchCount = 0, presetNames = {};
function paintWatchCount() {
  const name = presetNames[getPreset()];
  $("#watch-count").textContent = `${watchCount}개 종목${name ? ` · 매력도 ${name} 기준` : ""}`;
}
const presetBox = h('<div id="preset-menu"></div>');
$("#watch-count").before(presetBox);
loadPresets().then(({ presets }) => {
  presetNames = Object.fromEntries(presets.map((p) => [p.code, p.name]));
  paintWatchCount();
});
mountPresetMenu(presetBox);
document.addEventListener(PRESET_EVENT, loadWatchlist);   // 지수·환율은 성향과 무관해서 관심종목만 다시 조회

// ── [S5-A] 순위 상위 5 (GET /statistics/ranking) ──
// index.html은 A의 담당 파일이 아니라서, 이 파일이 관심종목 아래에 칸을 만들어 붙인다.
// 행 = 순위 · 종목명(티커·시장 배지) · 그 탭의 순위 근거 값 하나. 거래량은 시장을 정해야 해서 국내/미국 탭이 항상 하나 선택돼 있다
const RANK_METRICS = [
  { value: "volume", label: "거래량" },
  { value: "return_1m", label: "1개월 수익률" },
  { value: "return_1y", label: "1년 수익률" },
];
let rankMetric = "volume";
let rankCountry = "KR";

const rankSection = h(`<section class="section" aria-labelledby="h-rank">
    <div class="section__head"><h2 id="h-rank">순위 상위 5 <span class="section__meta">일봉 기준</span></h2>
      <div class="section__tools"><div id="rank-metric"></div><div id="rank-country"></div></div></div>
    <div id="rank-list"></div></section>`);
$("#watchlist").closest("section").after(rankSection);

function rankValue(i) {
  const text = rankMetric === "volume" ? volume(i.value) : pct(i.value, { sign: true, digits: 1 });
  const cls = rankMetric === "volume" ? "" : i.value > 0 ? " chg--up" : i.value < 0 ? " chg--down" : "";
  return `<span class="row__value num${cls}" title="기준일 ${esc(shortDate(i.as_of))}">${text}</span>`;
}

function rankRow(i) {
  return h(`<li><a class="row" href="${stockUrl(i.market, i.ticker)}">
      <span class="rank">${i.rank}</span>
      <span class="row__main"><span class="row__title">${esc(i.name)}</span>
        <span class="row__sub">${esc(i.ticker)} ${marketBadge(i.market, i.country)}</span></span>
      ${rankValue(i)}
    </a></li>`);
}

function loadRanking() {
  return load($("#rank-list"), {
    skeleton: skeleton("row", 5),
    fetch: async () => (await getRanking(rankMetric, rankCountry, 5)).items,
    render: (items) => {
      const ul = h('<ul class="list card card--flush"></ul>');
      ul.append(...items.map(rankRow));
      return ul;
    },
    empty: emptyState({ title: "순위를 매길 종목이 없습니다", body: "데이터 적재 후 다시 확인해 주세요." }),
  });
}

$("#rank-metric").append(segmented(RANK_METRICS, rankMetric,
  (v) => { rankMetric = v; loadRanking(); }, { label: "순위 기준 선택" }));
$("#rank-country").append(segmented([{ value: "KR", label: "국내" }, { value: "US", label: "미국" }], rankCountry,
  (v) => { rankCountry = v; loadRanking(); }, { label: "순위 시장 선택" }));
loadRanking();
