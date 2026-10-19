// 대시보드 홈: 주요 지수 5개 + USD/KRW 카드 (값·등락·스파크라인) + 내 관심종목 카드
import { PRESET_EVENT, getFx, getIndices, getPortfolioSummary, getPortfolios, getPreset, getHomeRanking, getSectors, getSentiment, getWatchlist } from "../api.js";   // [S4-A] PRESET_EVENT·getPreset  [S6-A] getHomeRanking·getSectors·getSentiment · 포트폴리오 요약
import { DASH, changeHtml, changeLabel, date, dateTime, esc, krw, num, pct, price, shortDate, signedKrw, stockUrl, usd } from "../format.js";   // [S5-A] pct
import { color, destroyCharts, draw, scoreBand, scoreGauge, sparkline } from "../components/charts.js";   // [S4-A] scoreGauge
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";   // [S3-A] REFRESHED_EVENT
import { emptyState, errorState, h, load, marketBadge, segmented, skeleton } from "../components/ui.js";   // [S5-A] marketBadge
import { loadPresets, mountPresetMenu } from "../components/preset-menu.js";   // [S4-A]
import { FX_CODE, DEFAULT_METRICS, metricPicker, storedMetrics } from "../components/metric-picker.js";   // [S5-A]
import { openWatchNote } from "../components/watch-note.js";   // [S5-A]
import { icons } from "../components/icons.js";   // [S5-A]
import { mountSearch } from "../components/search.js";   // [S6-A]

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

const FLAT_FX = 0.001;   // 환율 변동이 ±0.1% 미만이면 '보합'으로 보고 원화 관점 문구를 생략
const isNum = (v) => typeof v === "number" && Number.isFinite(v);   // [S6-A]
const monthDay = (iso) => (iso ? `${iso.slice(5, 7)}.${iso.slice(8, 10)}` : "");   // [S6-A]
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

/** 52주 저점~고점 사이 현재 위치 — 컴팩트 카드에서는 바 대신 값 줄 툴팁으로 보여 준다 */
function range52Title(low, high, pos, digits = 2) {
  if (!isNum(pos) || !isNum(low) || !isNum(high)) return "52주 범위: 1년치 데이터 부족";
  return `52주 저점 ${num(low, digits)} · 고점 ${num(high, digits)} · 현재 ${Math.round(Math.max(0, Math.min(1, pos)) * 100)}% 위치`;
}

// 컴팩트 지수 카드: 이름(+장 상태 배지) · 값과 등락률 한 줄 · 스파크라인. 기간은 섹션 상단 탭, 기준일·52주는 툴팁
function indexCard(ix) {
  const badge = sessionBadge(ix);
  const el = h(`<article class="metric-card" aria-label="${esc(ix.name)}">
      <div class="metric-card__label"><span title="${esc(ix.name)}">${esc(ix.name)}</span>${badge || `<span class="subtle">${esc(ix.country || "")}</span>`}</div>
      <div class="metric-card__value-row" title="기준일 ${date(ix.as_of)} · ${range52Title(ix.low_52w, ix.high_52w, ix.position_52w)}">
        <span class="metric-card__value num">${num(ix.close, 2)}</span>${changeHtml(ix.change_rate, ix.country)}</div>
      <div class="metric-card__spark" title="${sparkMeta().label} 추이"><canvas aria-hidden="true"></canvas></div>
    </article>`);
  const closes = inRange(ix.sparkline || [], ix.as_of).map((p) => p.close);
  queueMicrotask(() => sparkline(el.querySelector("canvas"), closes, trendColor(ix.change_rate)));   // canvas가 붙은 뒤에 그린다
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
      <div class="metric-card__value-row" title="환율 기준 시각 ${dateTime(fx.rate_at)} · ${range52Title(fx.low_52w, fx.high_52w, fx.position_52w)}${note ? ` · ${note}` : ""}">
        <span class="metric-card__value num">${num(fx.usd_krw, 2)}<span class="subtle">원</span></span>${changeHtml(fx.change_rate, "KR")}</div>
      <div class="metric-card__spark" title="${sparkMeta().label} 추이"><canvas aria-hidden="true"></canvas></div>
    </article>`);
  // 현재값이 SNAPSHOT(장중 시각)일 때만 끝에 덧붙인다. DAILY면 이미 history의 마지막 점이라 덧붙이면 꼬리가 평평해진다
  const history = inRange(fx.history || [], localDay("Asia/Seoul", new Date(fx.rate_at))).map((p) => p.usd_krw);
  const values = fx.granularity === "SNAPSHOT" ? [...history, fx.usd_krw] : history;
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
  marketSummary();   // [S6-A]
}

$("#spark-range").append(segmented(SPARK_RANGES, sparkRange,
  (v) => { sparkRange = v; if (market.indices || market.fx) renderMarketRow(); }, { label: "스파크라인 기간" }));

// ── [S5-A] 표시 지표 선택 ──
// 버튼(#market-edit)과 상자 자리(#market-picker-slot)는 index.html에 있다 [S6-A]
const editBtn = $("#market-edit");
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
// [S6-A] 기본은 리스트(한 줄 목록, 값은 저장 호환을 위해 "compact"), 카드 보기로 바꿀 수 있다. 순서 바꾸기(▲▼)는 홈에서 뺐다(주식 리스트에서 한다)
let watchItems = null;

// [S5-A] 목표가 줄 — 괴리율(target_gap)은 서버가 계산한 값을 그대로 쓴다
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

// 편집 버튼(메모·목표가) — 링크 안에 버튼을 넣지 않도록 행·카드 링크의 형제로 둔다
function editButton(w) {
  const b = h(`<button class="wl-card__edit" type="button" aria-label="${esc(w.name)} 메모·목표가 편집" title="메모·목표가">${icons.edit}</button>`);
  b.addEventListener("click", () => openWatchNote(w, () => loadWatchlist()));   // [S5-A]
  return b;
}

// 카드 보기 = 요약: 게이지 · 티커 · 현재가·등락률 · 종목명 (목표가·메모는 리스트 보기에서)
function watchCard(w) {
  const el = h(`<div class="wl-item"><a class="wl-card card--link"
        href="${watchHref(w)}" aria-label="${esc(watchLabel(w))}">
      <div class="wl-card__gauge">${scoreGauge(w.score)}</div>
      <div class="wl-card__ticker">${esc(w.ticker)} · ${esc(w.market)}</div>
      <div class="wl-card__price num">${price(w.close, w.currency)}</div>
      <div class="wl-card__chg num">${changeHtml(w.change_rate, w.country)}</div>
      <div class="wl-card__foot"><span class="wl-card__name">${esc(w.name)}</span></div>
    </a></div>`);
  el.append(editButton(w));
  return el;
}

// 리스트 보기 한 줄 = 자세히: 종목명(코드·시장) | 매력도 게이지 | 현재가·전일 대비(금액·등락률) | 목표가·괴리율 | 메모 | 편집
function watchRow(w) {
  const diff = isNum(w.change) ? `${w.change > 0 ? "+" : ""}${price(w.change, w.currency)}` : DASH;
  const target = w.target_price != null
    ? `<span class="wl-compact__main">${price(w.target_price, w.currency)}</span><span class="wl-compact__sub">괴리 ${w.target_gap != null ? pct(w.target_gap, { sign: true, digits: 1 }) : DASH}</span>`
    : `<span class="wl-compact__main subtle">${DASH}</span><span class="wl-compact__sub">목표가 없음</span>`;
  const el = h(`<li class="wl-crow"><a class="row" href="${watchHref(w)}" aria-label="${esc(watchLabel(w))}">
      <span class="row__main"><span class="row__title">${esc(w.name)}</span>
        <span class="row__sub">${esc(w.ticker)} ${marketBadge(w.market, w.country)}</span></span>
      <span class="wl-compact__score">${scoreGauge(w.score)}</span>
      <span class="wl-compact__price num"><span class="wl-compact__main">${price(w.close, w.currency)}</span>
        <span class="wl-compact__sub">${changeHtml(w.change_rate, w.country)}<span class="wl-compact__diff"> · ${diff}</span></span></span>
      <span class="wl-compact__target num">${target}</span>
      <span class="wl-compact__memo${w.memo ? "" : " subtle"}" title="${esc(w.memo || "")}">${w.memo ? esc(w.memo) : "메모 없음"}</span>
    </a></li>`);
  el.append(editButton(w));
  return el;
}

// 모드별 표시 한도 — 리스트 최대 8행, 카드 4열×2줄(중간 폭 3열, 좁은 화면 2열). 넘으면 정렬 순서대로 자르고 '+N개 더'
const COMPACT_LIMIT = 8;
const cardCols = () => (window.innerWidth < 600 ? 2 : window.innerWidth < 1024 ? 3 : 4);   // .wl-grid--home 미디어 쿼리와 맞춤
const watchLimit = () => (watchView === "compact" ? COMPACT_LIMIT : cardCols() * 2);

// 보기 방식은 브라우저에 저장 — 기본은 리스트. 이전 키(watchView)의 값이 새 기본값을 덮지 않도록 새 키를 쓴다
const WATCH_VIEW_KEY = "watchViewHome";
function storedWatchView() {
  try { return localStorage.getItem(WATCH_VIEW_KEY) === "card" ? "card" : "compact"; } catch { return "compact"; }
}
let watchView = storedWatchView();

function renderWatchMore(items) {
  const more = $("#watch-more");
  const extra = (items?.length || 0) - watchLimit();
  more.hidden = extra <= 0;
  more.textContent = extra > 0 ? `+${extra}개 더 · 주식 리스트 →` : "";
}

function renderWatch(items) {
  watchCount = items.length;   // [S4-A]
  renderWatchSummary(items);   // [S6-A]
  paintWatchCount();
  renderWatchMore(items);
  const shownItems = items.slice(0, watchLimit());
  if (watchView === "compact") {
    const ul = h('<ul class="list card card--flush wl-compact" aria-label="내 관심종목"></ul>');
    ul.append(...shownItems.map(watchRow));
    return ul;
  }
  const grid = h('<div class="wl-grid wl-grid--home"></div>');
  grid.append(...shownItems.map(watchCard));
  return grid;
}

$("#watch-view").append(segmented([{ value: "compact", label: "리스트" }, { value: "card", label: "카드" }], watchView, (v) => {
  watchView = v;
  try { localStorage.setItem(WATCH_VIEW_KEY, v); } catch { /* 저장 불가면 이번 화면에서만 유지 */ }
  if (watchItems && watchItems.length) $("#watchlist").replaceChildren(renderWatch(watchItems));
}, { label: "관심종목 보기 방식" }));

async function loadWatchlist() {
  const items = await load($("#watchlist"), {
    skeleton: skeleton("row", 6),
    fetch: async () => (await getWatchlist()).items,
    render: (items) => {
      watchItems = items;
      return renderWatch(items);
    },
    empty: emptyState({ title: "관심종목이 없습니다", body: "주식 리스트나 상단 검색에서 종목을 찾아 ★를 누르면 여기에 모입니다.",
      action: '<a class="btn btn--primary" href="/stocks">주식 리스트로</a>' }),
  });
  watchItems = items;
  if (!items?.length) { renderWatchMore(null); renderWatchSummary(null); }
  return items;
}

// 카드 열 수가 바뀌는 폭(600px)을 넘나들면 한도가 달라지므로 다시 그린다
let watchColsLast = cardCols();
let watchResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(watchResizeTimer);
  watchResizeTimer = setTimeout(() => {
    const cols = cardCols();
    if (cols === watchColsLast || watchView !== "card" || !watchItems || !watchItems.length) return;
    watchColsLast = cols;
    $("#watchlist").replaceChildren(renderWatch(watchItems));
  }, 150);
});

loadWatchlist();

// ── [S3-A] 사이드바 새로고침이 끝나면 지수·환율·관심종목을 새 값으로 다시 불러온다 ──
document.addEventListener(REFRESHED_EVENT, () => { loadMarket(); loadWatchlist(); loadSectors(); loadSentiment(); loadTop(); loadPortfolioWidget(); });   // [S6-A] 섹터·심리·순위 · 포트폴리오 요약

// ── [S4-A] 투자 성향: 관심종목 카드의 매력도 게이지가 따르는 값 ──
// 성향 메뉴(#preset-menu)는 index.html에 자리가 있고, 아래에서 맨 위 검색바 줄로 옮긴다 [S6-A]
let watchCount = 0, presetNames = {};
function paintWatchCount() {
  const name = presetNames[getPreset()];
  $("#watch-count").textContent = `${watchCount}개 종목${name ? ` · 매력도 ${name} 기준` : ""}`;
}
const presetBox = $("#preset-menu");
loadPresets().then(({ presets }) => {
  presetNames = Object.fromEntries(presets.map((p) => [p.code, p.name]));
  paintWatchCount();
});
// ── [S6-A] 맨 위 한 줄: 상단 검색바 + 투자 성향 ──
mountSearch();   // .main__inner 맨 앞에 .topbar(검색바)를 붙인다
const topbar = $(".topbar");
if (topbar) { topbar.classList.add("topbar--home"); topbar.append(presetBox); }
mountPresetMenu(presetBox);
document.addEventListener(PRESET_EVENT, () => { loadWatchlist(); if (topKind === "attractiveness") loadTop(); });   // 지수·환율은 성향과 무관해서 관심종목(과 매력도 순위)만 다시 조회

// ── [S6-A] 섹터 히트맵 · 시장 심리 지수 ──
// ---------------------------------------------------------------- 섹터 히트맵 (GET /home/sectors — DB만 읽음, 수집은 갱신 작업)
// 타일 = 섹터명 + 등락률. 크기는 섹터 가중치(근사치, 서버 상수), 색은 부호(상승 --up / 하락 --down)와 크기(±3%에서 최대 농도)
const HEAT_FULL = 3;
let sectorCountry = "KR";

function heatTile(s) {
  const c = s.change_pct;
  const label = isNum(c) ? `${s.name} ${changeLabel(c / 100)}` : `${s.name} 데이터 없음`;
  let bg = "var(--card-active)";
  if (isNum(c) && c !== 0) {
    const mix = Math.round(18 + 72 * Math.min(Math.abs(c) / HEAT_FULL, 1));
    bg = `color-mix(in srgb, var(${c > 0 ? "--heat-up" : "--heat-down"}) ${mix}%, var(--surface))`;
  }
  const chg = !isNum(c) ? "–" : `${c > 0 ? "▲" : c < 0 ? "▼" : ""}${pct(Math.abs(c) / 100)}`;
  return `<div class="heat__tile" role="listitem" aria-label="${esc(label)}"
      style="flex:${s.weight} 1 ${(s.weight * 0.9).toFixed(1)}%;background:${bg}">
      <span class="heat__name">${esc(s.name)}</span><span class="heat__chg num">${chg}</span></div>`;
}

function renderSectors(d) {
  const foot = $("#sector-foot");
  if (!d.available) {
    foot.replaceChildren();
    return emptyState({ title: `${d.country === "KR" ? "국내" : "미국"} 섹터 데이터 준비 중`,
      body: d.country === "KR" ? "KRX 섹터 지수를 아직 받지 못했습니다. 미국 탭은 볼 수 있습니다." : "다음 갱신 때 섹터 등락률을 받습니다." });
  }
  foot.innerHTML = `<span>기준일 ${esc(monthDay(d.as_of))}</span>${sessionBadge({ as_of: d.as_of, country: d.country, session_status: d.session_status })}`;
  const el = h(`<div class="heat" role="list" aria-label="${d.country === "KR" ? "국내" : "미국"} 섹터 전일 대비 등락률"></div>`);
  el.innerHTML = [...d.sectors].sort((a, b) => b.weight - a.weight).map(heatTile).join("");
  return el;
}

const sectorTabs = segmented([{ value: "KR", label: "국내" }, { value: "US", label: "미국" }], sectorCountry,
  (v) => { sectorCountry = v; loadSectors(); }, { label: "섹터 시장 선택" });
$("#sector-tabs").append(sectorTabs);

async function loadSectors({ fallback = false } = {}) {
  const box = $("#sectors");
  box.replaceChildren(h('<div class="skeleton heat-skeleton" aria-busy="true" aria-label="불러오는 중"></div>'));
  try {
    let d = await getSectors(sectorCountry);
    // 처음 열 때 국내 데이터가 없으면 미국으로 시작
    if (fallback && !d.available && sectorCountry === "KR") {
      const us = await getSectors("US");
      if (us.available) { sectorCountry = "US"; sectorTabs.setValue("US"); d = us; }
    }
    box.replaceChildren(renderSectors(d));
  } catch (err) {
    $("#sector-foot").replaceChildren();
    box.replaceChildren(errorState(err, () => loadSectors()));
  }
}

// ---------------------------------------------------------------- 시장 심리 지수 (GET /home/sentiment — StockMind 간이 계산, CNN Fear & Greed 아님)
const SENTIMENT_LABELS = ["극단적 공포", "공포", "중립", "탐욕", "극단적 탐욕"];
let sentimentCountry = "KR";

function sentimentHistory(name, p) {
  return `<div class="senti__hist-item"><dt>${name}</dt><dd>${p
    ? `<strong class="num">${Math.round(p.score)}</strong> <span>${esc(p.label)}</span>` : "–"}</dd></div>`;
}

function renderSentiment(d) {
  if (!isNum(d.score)) {
    return emptyState({ title: "데이터 부족", body: "심리 지수를 계산할 지수 일봉이 부족합니다." });
  }
  const c = d.components;
  const parts = [["가격 위치 (52주)", c.price_position], ["이동평균 괴리 (125일)", c.ma_gap_score], ["RSI (14일)", c.rsi_score]];
  if (d.market === "US") parts.push(["변동성 (VIX)", c.vix_score]);
  const index = d.index_code === "SPX" ? "S&P 500" : "KOSPI";
  // 게이지 + 어제·지난주를 한 묶음으로 가운데 두고, 기준일 줄은 칸 맨 아래 (구간 이름은 게이지 색·라벨이 보여 준다)
  return h(`<div class="senti">
      <div class="senti__main">
        <div class="senti__gauge" tabindex="0" aria-describedby="senti-tip"
             aria-label="시장 심리 지수 ${Math.round(d.score)}점 ${esc(d.label)}">
          ${scoreGauge(d.score, { labels: SENTIMENT_LABELS })}
          <div class="senti__tip" role="tooltip" id="senti-tip"><strong>구성요소 점수 (0~100)</strong>
            ${parts.map(([n, v]) => `<span>${n}</span><span class="num">${isNum(v) ? Math.round(v) : "계산 불가"}</span>`).join("")}
          </div>
        </div>
        <dl class="senti__hist">${sentimentHistory("어제", d.previous)}${sentimentHistory("지난주", d.week_ago)}</dl>
      </div>
      <p class="home-widget__foot senti__foot"><span>${index} 기준 · 기준일 ${esc(monthDay(d.as_of))}</span>${
        sessionBadge({ as_of: d.as_of, country: d.market, session_status: d.session_status })}</p>
    </div>`);
}

$("#sentiment-tabs").append(segmented([{ value: "KR", label: "국내" }, { value: "US", label: "미국" }], sentimentCountry,
  (v) => { sentimentCountry = v; loadSentiment(); }, { label: "심리 지수 시장 선택" }));

function loadSentiment() {
  return load($("#sentiment"), {
    skeleton: h('<div class="skeleton senti-skeleton" aria-busy="true" aria-label="불러오는 중"></div>'),
    fetch: () => getSentiment(sentimentCountry),
    render: renderSentiment,
    isEmpty: () => false,
  });
}

// 처음 열 때: 국내 섹터 데이터가 없으면 미국 탭으로 시작
loadSectors({ fallback: true });
loadSentiment();

// ---------------------------------------------------------------- 내 포트폴리오 요약 (GET /portfolios · /portfolios/{id}/summary — 포트폴리오 화면과 같은 값)
// 총 평가금액(담은 종목 + 현금) · 평가손익 + 종목·현금 비중 도넛과 범례 · 시드 사용률. 편집은 포트폴리오 화면에서 한다
const PF_TOP = 9;   // 범례·도넛에 따로 보여 줄 종목 수 — 나머지는 "외 n개"로 묶는다
const PF_KEY = "homePortfolio";   // 고른 포트폴리오는 브라우저에 저장(없거나 지워졌으면 첫 번째)
const PF_COLORS = ["#2bb3a3", "#5ea8ff", "#b39ddb", "#f5c26b", "#f0729a", "#4fd1c5", "#9ccc65", "#ff9f5a", "#7986cb", "#e6ddf2"];
const pfPnlClass = (v) => (v > 0 ? "chg chg--kr-up" : v < 0 ? "chg chg--kr-down" : "chg chg--flat");   // 원화 손익은 국내 관례 색(포트폴리오 화면과 같음)
const pfPnlHtml = (v, rate) => (v === null ? DASH : `<span class="${pfPnlClass(v)}">${signedKrw(v)}${isNum(rate) ? ` (${pct(rate, { sign: true })})` : ""}</span>`);
let pfId = null;

function storedPortfolioId() {
  try { return Number(localStorage.getItem(PF_KEY)) || null; } catch { return null; }
}

// 도넛·범례 조각 = 평가금액 큰 순 종목(시세 없으면 원가) + "외 n개" + 현금. 비중 = 총 평가금액(현금 포함) 대비
function pfSlices(s) {
  const items = s.items.map((it) => ({ ...it, amount: it.value_krw ?? it.cost_krw })).sort((a, b) => b.amount - a.amount);
  const slices = items.slice(0, PF_TOP).map((it, i) => ({ name: it.name, market: it.market, ticker: it.ticker, amount: it.amount, color: PF_COLORS[i % PF_COLORS.length] }));
  const rest = items.slice(PF_TOP);
  if (rest.length) slices.push({ name: `외 ${rest.length}개`, amount: rest.reduce((a, it) => a + it.amount, 0), color: color("--text-2") });
  if (s.remaining_krw > 0) slices.push({ name: "현금", amount: s.remaining_krw, color: color("--card-active") });
  const total = slices.reduce((a, x) => a + x.amount, 0);
  return slices.map((x) => ({ ...x, share: total > 0 ? x.amount / total : 0 }));
}

// 범례 한 줄: 색 · 이름(길면 말줄임, 전체는 툴팁) · 비중. 종목은 상세로 가는 링크
function pfLegendRow(x) {
  const inner = `<i style="background:${x.color}"></i><span class="home-pf__legend-name">${esc(x.name)}</span><span class="home-pf__legend-pct num">${pct(x.share, { digits: 1 })}</span>`;
  const title = esc(`${x.name} ${krw(x.amount)} (${pct(x.share, { digits: 1 })})`);
  return x.ticker
    ? `<a class="home-pf__legend-row" role="listitem" href="${stockUrl(x.market, x.ticker)}" title="${title}">${inner}</a>`
    : `<span class="home-pf__legend-row" role="listitem" title="${title}">${inner}</span>`;
}

function drawPfDonut(canvas, slices) {
  draw(canvas, {
    type: "doughnut",
    data: { labels: slices.map((x) => x.name), datasets: [{ data: slices.map((x) => x.amount), backgroundColor: slices.map((x) => x.color), borderWidth: 0, spacing: 1 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: "58%",
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.label} ${krw(ctx.raw)} (${pct(slices[ctx.dataIndex].share, { digits: 1 })})` } } } },
  });
}

function renderPortfolioWidget(s) {
  const usage = Math.min(1, s.usage_rate ?? 0);
  const items = s.items;
  const slices = pfSlices(s);
  const el = h(`<div class="home-pf__inner">
      <div class="home-pf__main">
        <div class="home-pf__left">
          <div class="home-pf__hero">
            <span class="subtle">총 평가금액</span>
            <strong class="home-pf__big num">${krw(s.total_value_krw + s.remaining_krw)}</strong>
            <span class="home-pf__total-pnl num">${items.length ? pfPnlHtml(s.total_pnl_krw, s.total_pnl_rate) : "담은 종목 없음"}</span>
          </div>
          ${items.length ? `<div class="home-pf__legend" role="list" aria-label="평가금액 비중">${slices.map(pfLegendRow).join("")}</div>` : ""}
        </div>
        ${items.length ? `<div class="home-pf__donut"><canvas role="img" aria-label="종목·현금 평가금액 비중 도넛 차트"></canvas>
          <div class="home-pf__donut-center"><span class="subtle">종목 평가</span><strong class="num">${krw(s.total_value_krw, { compact: true })}</strong></div></div>` : ""}
      </div>
      <span class="home-pf__usage subtle">시드 ${krw(s.seed_krw, { compact: true })} 중 ${pct(usage, { digits: 1 })} 사용 · 현금 ${krw(s.remaining_krw, { compact: true })}</span>
    </div>`);
  if (!items.length) {
    el.append(emptyState({ title: "아직 담은 종목이 없습니다", body: "주식 리스트나 종목 상세에서 종목을 담아 보세요.",
      action: '<a class="btn btn--primary" href="/stocks">주식 리스트로</a>' }));
    return el;
  }
  el.append(h(`<p class="home-widget__foot">모의 계산 · 체결 기록 아님${s.as_of ? ` · 기준일 ${esc(monthDay(s.as_of))}` : ""}</p>`));
  return el;
}

async function loadPortfolioSummary() {
  const box = $("#pf-summary");
  $("#pf-more").href = `/portfolio?id=${pfId}`;
  destroyCharts(box);
  box.replaceChildren(skeleton("row", 4));
  try {
    const s = await getPortfolioSummary(pfId);
    box.replaceChildren(renderPortfolioWidget(s));
    const canvas = box.querySelector(".home-pf__donut canvas");   // 도넛은 화면에 붙은 뒤 그려야 크기를 잡는다
    if (canvas) drawPfDonut(canvas, pfSlices(s));
  } catch (err) {
    box.replaceChildren(errorState(err, loadPortfolioSummary));
  }
}

async function loadPortfolioWidget() {
  const box = $("#pf-summary");
  box.replaceChildren(skeleton("row", 4));
  let list;
  try {
    list = await getPortfolios();
  } catch (err) {
    $("#pf-tabs").replaceChildren();
    box.replaceChildren(errorState(err, loadPortfolioWidget));
    return;
  }
  if (!list.length) {
    $("#pf-tabs").replaceChildren();
    $("#pf-more").href = "/portfolio";
    box.replaceChildren(emptyState({ title: "포트폴리오가 없습니다", body: "시드(투자 가능 금액)를 정해 모의 포트폴리오를 만들어 보세요.",
      action: '<a class="btn btn--primary" href="/portfolio">포트폴리오 만들기</a>' }));
    return;
  }
  const wanted = pfId ?? storedPortfolioId();
  pfId = list.some((p) => p.portfolio_id === wanted) ? wanted : list[0].portfolio_id;
  // 여러 개면 탭으로 고른다
  $("#pf-tabs").replaceChildren(...(list.length > 1 ? [segmented(list.map((p) => ({ value: p.portfolio_id, label: p.name })), pfId, (v) => {
    pfId = v;
    try { localStorage.setItem(PF_KEY, String(v)); } catch { /* 저장 불가면 이번 화면에서만 유지 */ }
    loadPortfolioSummary();
  }, { label: "포트폴리오 선택" })] : []));
  loadPortfolioSummary();
}

loadPortfolioWidget();

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
    fetch: async () => (await getHomeRanking(topKind, topCountry, 5)).items,
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

loadTop();
