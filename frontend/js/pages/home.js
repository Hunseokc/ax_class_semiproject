// 대시보드 홈: 지수·환율 카드(표시 지표 선택·시장 요약), 내 관심종목(카드/컴팩트), 시장 주목 종목 TOP 5(거래량 급증·매력도)
import { Home, Market, PRESET_EVENT, Watchlist, getPreset } from "../api.js";
import { changeHtml, changeLabel, date, dateTime, esc, formatPriceWithChange, num, pct, price, shortDate, stockUrl } from "../format.js";
import { color, destroyCharts, sparkline } from "../components/charts.js";
import { icons } from "../components/icons.js";
import { DEFAULT_METRICS, FX_CODE, metricPicker, storedMetrics } from "../components/metric-picker.js";
import { openWatchNote } from "../components/watch-note.js";
import { loadPresets, mountPresetMenu } from "../components/preset-menu.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";
import { emptyState, h, load, marketBadge, scoreBadge, scoreBand, scoreGauge, segmented, skeleton } from "../components/ui.js";

mountSidebar("home");

const $ = (sel) => document.querySelector(sel);
// 등락 색은 시장과 무관하게 상승 --up(빨강)·하락 --down(파랑)
const trendColor = (rate) => (!rate ? color("--text-2") : color(rate > 0 ? "--up" : "--down"));

// ---------------------------------------------------------------- 지수·환율
// 스파크라인 기간 — API는 1년치를 주고 화면에서 자른다(일봉 기준이라 '1일'은 없음). 기본 1개월(이전 30거래일 표시에 가장 가까움)
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

const FLAT_FX = 0.001;   // 환율 변동이 ±0.1% 미만이면 '보합'으로 보고 원화 관점 문구를 생략
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const localDay = (tz, at = new Date()) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(at);   // YYYY-MM-DD

/** 최신 데이터 날짜가 그 시장의 오늘이 아니면 배지. 판정은 서버의 거래소 달력(session_status),
 *  서버가 판정하지 못하면(null) 주말 여부로만 판단한다 */
function sessionBadge(ix) {
  if (!ix.as_of) return "";
  let status = ix.session_status;
  if (!status) {
    const today = localDay(ix.country === "US" ? "America/New_York" : "Asia/Seoul");
    const dow = new Date(`${today}T00:00:00Z`).getUTCDay();
    status = ix.as_of >= today ? "today" : dow === 0 || dow === 6 ? "holiday" : "previous_session";
  }
  if (status === "today") return "";
  const [text, why] = status === "holiday"
    ? ["휴장", "오늘은 휴장일(거래소 달력 기준)이라 마지막 거래일 종가를 표시합니다"]
    : ["직전 거래일", "오늘 일봉이 아직 없어 직전 거래일 종가를 표시합니다(일봉 기준)"];
  return `<span class="badge badge--market" title="${why}">${text}</span>`;
}

/** 52주 저점~고점 사이 현재 위치 바. 1년치가 없으면 같은 높이의 안내 줄(카드 높이 유지) */
function range52(low, high, pos, digits = 2) {
  if (!isNum(pos) || !isNum(low) || !isNum(high)) {
    return '<div class="r52 r52--na"><span class="r52__lbl">52주</span><span>1년치 데이터 부족</span></div>';
  }
  const p = Math.max(0, Math.min(1, pos)) * 100;
  return `<div class="r52" role="img" aria-label="52주 범위 ${num(low, digits)}~${num(high, digits)} 중 ${Math.round(p)}% 위치"
      title="52주 저점 ${num(low, digits)} · 고점 ${num(high, digits)} · 현재 ${Math.round(p)}% 위치">
      <span class="r52__lbl">52주</span><span class="r52__track"><i class="r52__dot" style="left:${p.toFixed(1)}%"></i></span></div>`;
}

function indexCard(ix) {
  const el = h(`<article class="metric-card" aria-label="${esc(ix.name)}">
      <div class="metric-card__label"><span title="${esc(ix.name)}">${esc(ix.name)}</span><span class="subtle">${esc(ix.country || "")}</span></div>
      <div class="metric-card__value num">${num(ix.close, 2)}</div>
      <div class="metric-card__spark"><canvas aria-hidden="true"></canvas></div>
      <div class="metric-card__meta"><span>${sparkMeta().label} 추이</span>${sessionBadge(ix)}</div>
      ${range52(ix.low_52w, ix.high_52w, ix.position_52w)}
      <div class="metric-card__foot">${changeHtml(ix.change_rate, ix.country)}<span class="subtle" title="기준일 ${date(ix.as_of)}">${shortDate(ix.as_of)}</span></div>
    </article>`);
  const closes = inRange(ix.sparkline || [], ix.as_of).map((p) => p.close);
  queueMicrotask(() => sparkline(el.querySelector("canvas"), closes, trendColor(ix.change_rate)));
  return el;
}

/** 원화 관점 한 줄: 환율 상승(원화 약세)은 미국 종목의 원화 환산에 유리, 하락은 불리. 변동이 작으면 생략 */
function fxNote(rate) {
  if (!isNum(rate) || Math.abs(rate) < FLAT_FX) return "";
  return `미국 종목 원화 환산에 소폭 ${rate > 0 ? "유리" : "불리"}`;
}

function fxCard(fx) {
  const note = fxNote(fx.change_rate);
  const el = h(`<article class="metric-card" aria-label="원달러 환율">
      <div class="metric-card__label"><span>USD/KRW</span>${fx.fx_stale ? '<span class="badge badge--market" title="최신 환율을 가져오지 못해 마지막 값을 표시합니다">지연</span>' : '<span class="subtle">환율</span>'}</div>
      <div class="metric-card__value num">${num(fx.usd_krw, 2)}<span class="subtle">원</span></div>
      <div class="metric-card__spark"><canvas aria-hidden="true"></canvas></div>
      <div class="metric-card__meta"><span>${sparkMeta().label} 추이</span></div>
      ${range52(fx.low_52w, fx.high_52w, fx.position_52w)}
      <div class="metric-card__foot">${changeHtml(fx.change_rate, "KR")}<span class="subtle" title="환율 기준 시각 ${dateTime(fx.rate_at)}">${dateTime(fx.rate_at).slice(-5)}</span></div>
      ${note ? `<div class="metric-card__note">${note}</div>` : ""}
    </article>`);
  const values = [...inRange(fx.history || [], localDay("Asia/Seoul", new Date(fx.rate_at))).map((p) => p.usd_krw), fx.usd_krw];
  queueMicrotask(() => sparkline(el.querySelector("canvas"), values, color("--lavender")));
  return el;
}

// ---------------------------------------------------------------- 한 줄 시장 요약 (규칙 기반 문장 조합, 조각별 데이터가 없으면 그 조각만 생략)
const direction = (r) => (r > 0 ? 1 : r < 0 ? -1 : 0);
function together(list) {
  const d = list.map((i) => direction(i.change_rate));
  if (d.every((x) => x === 1)) return "동반 상승";
  if (d.every((x) => x === -1)) return "동반 하락";
  if (d.every((x) => x === 0)) return "보합";
  return "혼조";
}
const monthDay = (iso) => (iso ? `${iso.slice(5, 7)}.${iso.slice(8, 10)}` : "");

function marketSummary() {
  const byCode = new Map((market.indices || []).map((i) => [i.code, i]));
  // 그룹의 지수가 하나라도 없거나 등락이 없으면 '동반'을 말할 수 없으므로 그 조각을 뺀다
  const group = (codes) => {
    const list = codes.map((c) => byCode.get(c));
    return list.every((i) => i && isNum(i.change_rate)) ? list : null;
  };
  const kr = group(["KOSPI", "KOSDAQ"]);
  const us = group(["SPX", "IXIC", "DJI"]);
  const datesDiffer = kr && us && kr[0].as_of !== us[0].as_of;
  const prefix = (list) => (datesDiffer ? `<span class="market-brief__date">${monthDay(list[0].as_of)}</span> ` : "");
  const parts = [];
  if (kr) parts.push(`${prefix(kr)}코스피·코스닥 ${together(kr)}`);
  if (us) parts.push(`${prefix(us)}미국 3대 지수 ${together(us)}`);
  const r = market.fx?.change_rate;
  if (isNum(r)) parts.push(Math.abs(r) < FLAT_FX ? "환율 보합" : r < 0 ? "원화 강세" : "원화 약세");
  const el = $("#market-summary");
  el.innerHTML = parts.join('<span class="market-brief__sep" aria-hidden="true"> · </span>');
  el.hidden = !parts.length;
}

/** "내 관심종목 N개 중 M개 하락(또는 상승)" — 많은 쪽을 보여 준다(같으면 상승). 비었거나 등락이 모두 없으면 숨김 */
function renderWatchSummary(items) {
  const el = $("#watch-summary");
  const up = (items || []).filter((w) => isNum(w.change_rate) && w.change_rate > 0).length;
  const down = (items || []).filter((w) => isNum(w.change_rate) && w.change_rate < 0).length;
  el.hidden = !items?.length || (!up && !down);
  if (el.hidden) return;
  const [m, word, cls] = down > up ? [down, "하락", "chg--down"] : [up, "상승", "chg--up"];
  el.innerHTML = `내 관심종목 ${items.length}개 중 <strong class="chg ${cls}">${m}개 ${word}</strong>`;
}

// 마지막 응답 — 표시 지표를 바꿀 때는 다시 요청하지 않고 이 값으로 다시 그린다
let market = { indices: null, fx: null, error: null };
let shown = [];

const availableMetrics = () => [...(market.indices || []).map((i) => i.code), FX_CODE];

function metricGroups() {
  const by = (country) => market.indices.filter((i) => i.country === country).map((i) => ({ code: i.code, name: i.name }));
  return [{ label: "국내", items: by("KR") }, { label: "미국", items: by("US") },
    { label: "환율", items: [{ code: FX_CODE, name: "USD/KRW" }] }].filter((g) => g.items.length);
}

function renderMarketRow() {
  const box = $("#market");
  destroyCharts(box);
  const row = h('<div class="metric-row"></div>');
  const byCode = new Map((market.indices || []).map((i) => [i.code, i]));
  for (const code of shown) {
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
  marketSummary();
}

function togglePicker(open, { focus = true } = {}) {
  const btn = $("#market-edit");
  const panel = $("#market-picker");
  if (!panel) return;
  panel.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
  if (focus) (open ? panel.querySelector(".chip:not(:disabled)") : btn)?.focus();
}

function mountPicker() {
  const btn = $("#market-edit");
  const wasOpen = btn.getAttribute("aria-expanded") === "true";
  shown = storedMetrics(availableMetrics());
  // 지수 목록을 못 받으면 고를 수 없다(저장된 선택을 덮어쓰지 않도록 설정을 막음)
  if (!market.indices) {
    $("#market-picker-slot").replaceChildren();
    btn.disabled = true;
    btn.setAttribute("aria-expanded", "false");
    return;
  }
  $("#market-picker-slot").replaceChildren(metricPicker({
    id: "market-picker", groups: metricGroups(), selected: shown,
    onChange: (codes) => { shown = codes; renderMarketRow(); },
    onClose: () => togglePicker(false),
  }));
  btn.disabled = false;
  togglePicker(wasOpen, { focus: false });
}

async function loadMarket() {
  const box = $("#market");
  destroyCharts(box);
  const sk = skeleton("card", shown.length || DEFAULT_METRICS.length);
  sk.className = "metric-row";
  box.replaceChildren(sk);
  const [ix, fx] = await Promise.allSettled([Market.indices(), Market.fx()]);
  market = {
    indices: ix.status === "fulfilled" ? ix.value.indices : null,
    fx: fx.status === "fulfilled" ? fx.value : null,
    error: ix.status === "rejected" ? ix.reason : fx.status === "rejected" ? fx.reason : null,
  };
  if (market.indices) $("#as-of").textContent = `일봉 기준 · 기준일 ${date(ix.value.as_of)}`;
  mountPicker();
  renderMarketRow();
}

$("#spark-range").append(segmented(SPARK_RANGES, sparkRange,
  (v) => { sparkRange = v; if (market.indices || market.fx) renderMarketRow(); }, { label: "스파크라인 기간" }));
$("#market-edit").addEventListener("click", () => togglePicker($("#market-edit").getAttribute("aria-expanded") !== "true"));

// ---------------------------------------------------------------- 관심종목
const watchTarget = (w) => (w.target_price != null
  ? `목표 ${price(w.target_price, w.currency)} (${w.target_gap != null ? pct(w.target_gap, { sign: true, digits: 1 }) : "–"})` : "");

function watchLabel(w) {
  const band = scoreBand(w.score);
  const target = watchTarget(w);
  return `${w.name}, ${price(w.close, w.currency)}, ${changeLabel(w.change_rate)}, `
    + (band ? `매력도 ${Math.round(w.score)}점 ${band.label}` : "매력도 데이터 부족")
    + (target ? `, ${target}` : "") + (w.memo ? `, 메모 ${w.memo}` : "");
}

// 상세 화면이 같은 투자 성향 탭이 선택된 상태로 열리도록 preset을 링크에 싣는다
const watchHref = (w) => `${stockUrl(w.market, w.ticker)}?preset=${encodeURIComponent(getPreset())}`;

function watchCard(w) {
  const target = watchTarget(w);
  // 링크 안에 버튼을 넣지 않도록 편집 버튼은 카드 링크의 형제로 둔다. 카드 배경은 한 톤(아이스)으로 통일
  const el = h(`<div class="wl-item"><a class="wl-card card--link card--ice"
        href="${watchHref(w)}" aria-label="${esc(watchLabel(w))}">
      <div class="wl-card__gauge">${scoreGauge(w.score)}</div>
      <div class="wl-card__ticker">${esc(w.ticker)} · ${esc(w.market)}</div>
      <div class="wl-card__price">${formatPriceWithChange(w.close, w.currency, w.change_rate)}</div>
      ${target ? `<div class="wl-card__note">${esc(target)}</div>` : ""}
      ${w.memo ? `<div class="wl-card__note wl-card__memo" title="${esc(w.memo)}">${esc(w.memo)}</div>` : ""}
      <div class="wl-card__foot"><span class="wl-card__name">${esc(w.name)}</span></div>
    </a>
    <button class="wl-card__edit" type="button" aria-label="${esc(w.name)} 메모·목표가 편집" title="메모·목표가">${icons.edit}</button></div>`);
  el.querySelector("button").addEventListener("click", () => openWatchNote(w, () => loadWatchlist()));
  return el;
}

async function renderWatchBasis() {
  const { presets } = await loadPresets();
  const p = presets.find((x) => x.code === getPreset());
  $("#watch-basis").textContent = p ? `· ${p.name}형 기준` : "";
}

// .wl-grid의 미디어 쿼리(768/1024/1440px)와 맞춘 열 수 — 항상 2줄만 보이도록 자른다
function watchCols() {
  const w = window.innerWidth;
  if (w >= 1440) return 5;
  if (w >= 1024) return 4;
  if (w >= 768) return 3;
  return 2;
}

// 컴팩트 보기 한 줄: 종목명 | 매력도 점수·라벨 | 가격 | 등락률 | 작은 스파크라인
function watchRow(w) {
  const band = scoreBand(w.score);
  const el = h(`<li><a class="row" href="${watchHref(w)}" aria-label="${esc(watchLabel(w))}">
      <span class="row__main"><span class="row__title">${esc(w.name)}</span>
        <span class="row__sub">${esc(w.ticker)} ${marketBadge(w.market, w.country)}</span></span>
      <span class="wl-compact__score">${scoreBadge(w.score)}<span class="wl-compact__band">${band
        ? `<i style="background:var(--gauge-${band.index})"></i>${band.label}` : "데이터 부족"}</span></span>
      <span class="wl-compact__price num">${price(w.close, w.currency)}</span>
      <span class="wl-compact__chg num">${changeHtml(w.change_rate, w.country)}</span>
      <span class="wl-compact__spark" aria-hidden="true"><canvas></canvas></span>
    </a></li>`);
  const closes = (w.sparkline || []).map((p) => p.close);
  if (closes.length > 1) queueMicrotask(() => sparkline(el.querySelector("canvas"), closes, trendColor(w.change_rate)));
  return el;
}

// 보기 방식(카드/컴팩트)은 브라우저에 저장 — 기본은 카드
const WATCH_VIEW_KEY = "watchView";
function storedWatchView() {
  try { return localStorage.getItem(WATCH_VIEW_KEY) === "compact" ? "compact" : "card"; } catch { return "card"; }
}
let watchView = storedWatchView();
let watchItems = null;

function renderWatch(items) {
  destroyCharts($("#watchlist"));
  if (watchView === "compact") {
    const ul = h('<ul class="list card card--flush wl-compact"></ul>');
    ul.append(...items.map(watchRow));
    return ul;
  }
  const grid = h('<div class="wl-grid"></div>');
  grid.append(...items.slice(0, watchCols() * 2).map(watchCard));
  return grid;
}

$("#watch-view").append(segmented([{ value: "card", label: "카드" }, { value: "compact", label: "컴팩트" }], watchView, (v) => {
  watchView = v;
  try { localStorage.setItem(WATCH_VIEW_KEY, v); } catch { /* 저장 불가면 이번 화면에서만 유지 */ }
  if (watchItems && watchItems.length) $("#watchlist").replaceChildren(renderWatch(watchItems));
}, { label: "관심종목 보기 방식" }));

async function loadWatchlist() {
  const items = await load($("#watchlist"), {
    skeleton: skeleton("card", 4),
    fetch: async () => (await Watchlist.list()).items,
    render: (items) => {
      watchItems = items;
      return renderWatch(items);
    },
    empty: emptyState({ title: "관심종목이 없습니다", body: "주식 리스트에서 ★로 추가하세요.", action: '<a class="btn btn--primary" href="/stocks">주식 리스트로 가기</a>' }),
  });
  watchItems = items;
  renderWatchSummary(items);
  return items;
}

let watchCols_last = watchCols();
let watchResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(watchResizeTimer);
  watchResizeTimer = setTimeout(() => {
    const cols = watchCols();
    if (cols === watchCols_last || watchView !== "card" || !watchItems || !watchItems.length) return;
    watchCols_last = cols;
    $("#watchlist").replaceChildren(renderWatch(watchItems));
  }, 150);
});

// ---------------------------------------------------------------- 시장 주목 종목 TOP 5 (GET /home/ranking)
// 행 = 순위 · 종목명(종목코드·시장 배지, 관심종목이면 ★) · 그 탭의 순위 근거 값 하나. 가격·등락률은 관심종목·리스트에 있으므로 넣지 않는다
const TOP_KINDS = [
  { value: "volume_surge", label: "거래량 급증", empty: "20거래일 거래량이 쌓인 종목이 없습니다" },
  { value: "attractiveness", label: "매력도 순위", empty: "매력도 점수가 계산된 종목이 없습니다",
    note: "현재는 공개 재무·시세로 계산한 규칙 기반 점수이며 투자 권유가 아닙니다." },
];
let topCountry = "KR";
let topKind = "volume_surge";

function topValue(s) {
  if (topKind === "volume_surge") {
    return `<span class="row__value num" title="당일 거래량 ÷ 직전 20거래일 평균 (기준일 ${esc(shortDate(s.as_of))})">${num(s.value, 1)}배</span>`;
  }
  const band = scoreBand(s.value);
  return `<span class="row__value top-score"><strong class="num">${Math.round(s.value)}</strong>${band
    ? `<span class="wl-compact__band"><i style="background:var(--gauge-${band.index})"></i>${band.label}</span>` : ""}</span>`;
}

function topRow(s) {
  return h(`<li><a class="row" href="${stockUrl(s.market, s.ticker)}">
      <span class="rank">${s.rank}</span>
      <span class="row__main"><span class="row__title">${esc(s.name)}${s.is_watched
        ? ' <span class="top-star" role="img" aria-label="관심종목">★</span>' : ""}</span>
        <span class="row__sub">${esc(s.ticker)} ${marketBadge(s.market, s.country)}</span></span>
      ${topValue(s)}
    </a></li>`);
}

function loadTop() {
  const kind = TOP_KINDS.find((k) => k.value === topKind);
  $("#top-more").href = `/stocks?country=${topCountry}`;
  $("#top-note").textContent = kind.note || "";
  $("#top-note").hidden = !kind.note;
  return load($("#top-list"), {
    skeleton: skeleton("row", 5),
    fetch: async () => (await Home.ranking(topKind, topCountry, 5)).items,
    render: (items) => {
      const ul = h('<ul class="list card card--flush"></ul>');
      ul.append(...items.map(topRow));
      return ul;
    },
    empty: emptyState({ title: kind.empty, body: "데이터 적재 후 다시 확인해 주세요." }),
  });
}

$("#top-metric").append(segmented(TOP_KINDS, topKind,
  (v) => { topKind = v; loadTop(); }, { label: "순위 기준 선택" }));
$("#top-tabs").append(segmented([{ value: "KR", label: "국내" }, { value: "US", label: "미국" }], topCountry,
  (v) => { topCountry = v; loadTop(); }, { label: "순위 시장 선택" }));

function loadAll() {
  loadMarket();
  loadWatchlist();
  loadTop();
}

mountPresetMenu($("#preset-menu"));
renderWatchBasis();
document.addEventListener(PRESET_EVENT, () => { renderWatchBasis(); loadWatchlist(); if (topKind === "attractiveness") loadTop(); });
document.addEventListener(REFRESHED_EVENT, loadAll);
loadAll();
