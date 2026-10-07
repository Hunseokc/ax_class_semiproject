// 종목 상세: 헤더·가격 차트·핵심 지표·매력도·수치 분석·재무 추이·경쟁 비교·최근 공시
import { PRESET_EVENT, Stocks, getPreset } from "../api.js";
import { DASH, changeHtml, date, esc, krw, num, pct, price, stockUrl, usd } from "../format.js";
import { openAddToPortfolio } from "../components/add-to-portfolio.js";
import { loadPresets, mountPresetMenu } from "../components/preset-menu.js";
import { color, dashedAxis, draw, plainAxis } from "../components/charts.js";
import { icons } from "../components/icons.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";
import { emptyState, errorState, h, load, marketBadge, segmented, skeleton } from "../components/ui.js";
import { starButton } from "../components/watch.js";

mountSidebar("stocks");
const $ = (sel) => document.querySelector(sel);
const [, , MARKET, TICKER] = location.pathname.split("/").map(decodeURIComponent);
let stock = null;                       // 상세 응답 (헤더 로드 후)

const upColor = (c) => color(c === "US" ? "--us-up" : "--kr-up");
const downColor = (c) => color(c === "US" ? "--us-down" : "--kr-down");
const signColor = (v, c) => (v > 0 ? upColor(c) : v < 0 ? downColor(c) : color("--flat"));
const money = (v, cur, compact = true) => (cur === "USD" ? usd(v, { compact }) : krw(v, { compact }));

// ---------------------------------------------------------------- 헤더
function renderHeader(s) {
  document.title = `${s.name} (${s.ticker}) · Stock Board`;
  const el = h(`<header class="stock-head">
      <div class="stock-head__id">
        <p class="subtle">${esc(s.ticker)} ${marketBadge(s.market, s.country)} ${s.groups.map((g) => `<span class="badge badge--market">${esc(g.name)}</span>`).join(" ")}</p>
        <h1>${esc(s.name)}</h1>
        ${s.name_en && s.name_en !== s.name ? `<p class="subtle">${esc(s.name_en)}</p>` : ""}
      </div>
      <div class="stock-head__price">
        <p class="stock-head__value num">${price(s.close, s.currency)}</p>
        <p>${changeHtml(s.change_rate, s.country)} <span class="subtle">${s.change !== null ? `(${s.change > 0 ? "+" : ""}${s.currency === "USD" ? usd(s.change) : krw(s.change)})` : ""}</span></p>
        ${s.currency === "USD" ? `<p class="subtle num">≈ ${krw(s.close_krw)} · 환율 ${num(s.fx_rate, 2)}${s.fx_stale ? " (지연)" : ""}</p>` : ""}
        <p class="subtle">일봉 기준 · ${date(s.as_of)} 종가</p>
      </div>
      <div class="stock-head__actions"></div>
    </header>`);
  const actions = el.querySelector(".stock-head__actions");
  const add = h(`<button class="btn btn--accent" type="button">${icons.plus}<span>포트폴리오에 담기</span></button>`);
  add.addEventListener("click", () => openAddToPortfolio(s));
  actions.append(starButton(s, s.is_watched), add);
  $("#head").replaceChildren(el);
}

// ---------------------------------------------------------------- 가격 차트
let range = "3m";
function loadCandles() {
  return load($("#price-chart"), {
    skeleton: h('<div class="skeleton" style="height:280px"></div>'),
    fetch: () => Stocks.candles(MARKET, TICKER, range),
    isEmpty: (d) => !d.candles.length,
    empty: emptyState({ title: "해당 기간의 시세가 없습니다" }),
    render: (d) => {
      const box = h('<div class="chart-box"><canvas role="img" aria-label="종가와 거래량 차트"></canvas></div>');
      const c = d.candles;
      const first = c[0].close, last = c.at(-1).close;
      const line = signColor(last - first, stock.country);
      queueMicrotask(() => draw(box.querySelector("canvas"), {
        type: "bar",
        data: {
          labels: c.map((x) => x.date),
          datasets: [
            { type: "line", label: "종가", data: c.map((x) => x.close), borderColor: line, borderWidth: 2, pointRadius: 0, tension: 0.2, yAxisID: "y", order: 1 },
            { type: "bar", label: "거래량", data: c.map((x) => x.volume), backgroundColor: "rgba(230,221,242,.28)", borderRadius: 4, yAxisID: "v", order: 2 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          scales: {
            x: { ...plainAxis, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
            y: { ...dashedAxis, position: "right", ticks: { callback: (v) => money(v, stock.currency) } },
            v: { display: false, max: Math.max(...c.map((x) => x.volume)) * 4 },
          },
          plugins: { tooltip: { callbacks: {
            label: (ctx) => ctx.dataset.label === "종가" ? `종가 ${price(ctx.raw, stock.currency)}` : `거래량 ${num(ctx.raw)}주`,
          } } },
        },
      }));
      return box;
    },
  });
}
$("#range-tabs").append(segmented(["1m", "3m", "6m", "1y"].map((v) => ({ value: v, label: v.toUpperCase() })), range,
  (v) => { range = v; loadCandles(); }, { label: "차트 기간" }));

// ---------------------------------------------------------------- 분석 (핵심 지표·매력도·수치 분석)
const stat = (label, value, sub = "") => `<div class="stat"><span class="stat__label">${label}</span>
  <span class="stat__value num">${value}</span>${sub ? `<span class="stat__sub">${sub}</span>` : ""}</div>`;

function renderKeyMetrics(a) {
  const m = a.metrics;
  const pos = m.position_52w;
  const el = h(`<div class="stat-grid">
      ${stat("PER", m.per ? `${num(m.per, 2)}배` : DASH, m.per ? "" : "적자·미제공")}
      ${stat("PBR", m.pbr ? `${num(m.pbr, 2)}배` : DASH)}
      ${stat("ROE", pct(m.roe), a.fin_period_end ? `FY ${a.fin_period_end.slice(0, 4)} · ${esc(a.accounting_std || "")}` : "재무 없음")}
      ${stat("영업이익률", pct(m.operating_margin))}
      ${stat("시가총액", money(m.market_cap, a.currency), a.currency === "USD" ? `≈ ${krw(m.market_cap_krw, { compact: true })}` : "")}
      <div class="stat stat--wide"><span class="stat__label">52주 범위 (일중 고저)</span>
        <span class="stat__value num" style="font-size:var(--fs-md)">${price(m.low_52w, a.currency)} – ${price(m.high_52w, a.currency)}</span>
        ${pos !== null ? `<div class="range" role="img" aria-label="52주 범위 내 위치 ${pct(pos, { digits: 0 })}"><span class="range__dot" style="left:${(pos * 100).toFixed(1)}%"></span></div>
          <span class="stat__sub">범위 내 위치 ${pct(pos, { digits: 0 })}</span>` : '<span class="stat__sub">1년 시세 부족</span>'}</div>
    </div>`);
  $("#key-metrics").replaceChildren(el);
}

function gauge(score) {
  const v = score === null ? 0 : Math.max(0, Math.min(100, score));
  const len = Math.PI * 70;   // 반원 길이 (r=70)
  return `<svg class="gauge" viewBox="0 0 168 100" role="img" aria-label="${score === null ? "매력도 계산 불가" : `매력도 ${num(score, 1)}점`}">
      <path d="M14 90 A70 70 0 0 1 154 90" fill="none" stroke="${color("--card-active")}" stroke-width="14" stroke-linecap="round"/>
      <path d="M14 90 A70 70 0 0 1 154 90" fill="none" stroke="${color("--lavender")}" stroke-width="14" stroke-linecap="round"
        stroke-dasharray="${(len * v) / 100} ${len}"/>
      <text x="84" y="80" text-anchor="middle" font-size="30" font-weight="800">${score === null ? "–" : Math.round(score)}</text>
      <text x="84" y="97" text-anchor="middle" font-size="11" fill="${color("--text-3")}">/ 100</text>
    </svg>`;
}

const FACTOR_LABEL = { value: "가치", quality: "퀄리티", growth: "성장", safety: "안정성", momentum: "모멘텀" };
const SIGNED_METRICS = ["revenue_yoy", "eps_change_yield", "momentum"];
const rawFmt = (m) => (m.raw_value === null ? DASH
  : m.metric === "debt_ratio" ? `${num(m.raw_value, 2)}배`
  : pct(m.raw_value, { digits: 1, sign: SIGNED_METRICS.includes(m.metric) }));
const zFmt = (v) => {
  if (v === null) return DASH;
  const r = Math.round(v * 100) / 100;
  return r === 0 ? "0.00" : `${r > 0 ? "+" : ""}${num(r, 2)}`;
};
let presetList = null;                   // { note, presets } — 투자 성향 메뉴와 같은 데이터

function contribRow(k, f, maxAbs) {
  const name = `<span class="contrib__name">${FACTOR_LABEL[k]} <span class="subtle">${num(f.weight * 100, 0)}%</span></span>`;
  if (!f.available) return `<div class="contrib contrib--na">${name}<div class="contrib__track"><span class="contrib__axis"></span></div><span class="contrib__value">데이터 없음</span></div>`;
  if (f.contribution === null) return `<div class="contrib">${name}<div class="contrib__track"><span class="contrib__axis"></span></div><span class="contrib__value num">F ${zFmt(f.score)}</span></div>`;
  const c = f.contribution, w = (Math.abs(c) / maxAbs) * 50;
  return `<div class="contrib">${name}
      <div class="contrib__track" role="img" aria-label="${FACTOR_LABEL[k]} 기여도 ${zFmt(c)} (팩터 점수 ${zFmt(f.score)} × 가중치 ${num(f.effective_weight * 100, 0)}%)">
        <span class="contrib__axis"></span><span class="contrib__bar ${c < 0 ? "contrib__bar--neg" : ""}" style="${c < 0 ? "right" : "left"}:50%;width:${w.toFixed(1)}%"></span></div>
      <span class="contrib__value num">${zFmt(c)}</span></div>`;
}

function renderScore(a) {
  const s = a.attractiveness;
  if (!s.as_of) {
    $("#score").replaceChildren(emptyState({ title: "매력도가 아직 계산되지 않았습니다", body: "사이드바의 새로고침으로 점수를 계산할 수 있습니다." }));
    return;
  }
  const dq = s.data_quality || {};
  const market = s.rank?.country === "US" ? "미국" : "국내";
  const factors = Object.entries(s.factors);
  const maxAbs = Math.max(0.5, ...factors.map(([, f]) => Math.abs(f.contribution ?? 0)));
  const notes = [dq.score_null_reason, ...(dq.notes || [])].filter(Boolean);
  const el = h(`<div class="score-panel">
      <div class="score-panel__gauge">${gauge(s.score)}
        <p class="score-panel__rank">${s.rank ? `${market} 비교군 ${s.rank.total}개 중 <strong>${s.rank.position}위</strong>` : "순위 없음"}</p>
        ${s.rank ? `<p class="subtle">백분위 ${num(s.rank.percentile, 0)}</p>` : ""}
        <p class="subtle">데이터 충족도 ${s.factor_coverage}/${s.factor_total} 팩터</p>
        <p class="subtle">${esc(s.preset.name)} · ${date(s.as_of)} 기준</p></div>
      <div class="score-panel__factors">
        <h3>팩터 기여도 <span class="subtle">(유효 팩터 가중치 × 팩터 점수, 합 = 종합 ${zFmt(s.composite)})</span></h3>
        ${factors.map(([k, f]) => contribRow(k, f, maxAbs)).join("")}
        <p class="subtle">팩터 점수는 같은 시장 안 표준점수(Z) 단위입니다. 0이 시장 중앙, 음수 기여는 왼쪽으로 표시합니다.</p>
      </div></div>`);
  const rows = s.metrics.map((m) => `<tr title="${esc(dq.missing_metrics?.[m.metric] || "")}">
      <td>${esc(m.label)}${m.direction < 0 ? ' <span class="subtle">낮을수록 좋음</span>' : ""}</td>
      <td>${FACTOR_LABEL[m.factor]}</td><td class="num">${rawFmt(m)}</td>
      <td class="num">${zFmt(m.z_raw)}</td><td class="num">${zFmt(m.z_adj)}</td></tr>`).join("");
  el.append(h(`<div class="table-wrap"><table class="table table--metrics">
      <caption class="sr-only">매력도 지표별 원값과 표준점수</caption>
      <thead><tr><th scope="col">지표</th><th scope="col">팩터</th><th scope="col">원값</th><th scope="col">Z (시장 내)</th><th scope="col">Z (섹터 중립)</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`));
  if (notes.length || dq.missing_metrics) {
    const missing = Object.entries(dq.missing_metrics || {}).map(([k, v]) => `${esc(s.metrics.find((m) => m.metric === k)?.label || k)}: ${esc(v)}`);
    el.append(h(`<ul class="score-notes">${[...notes.map(esc), ...missing].map((t) => `<li>${t}</li>`).join("")}</ul>`));
  }
  el.append(h(`<details class="score-method"><summary>계산 방법</summary><p>${esc(s.method)}</p>
      <p>${esc(s.preset.description || "")} — ${esc(presetList?.note || "")}</p></details>`));
  el.append(h(`<p class="subtle">${esc(a.disclaimer)}</p>`));
  $("#score").replaceChildren(el);
}

async function loadScore() {
  $("#score").replaceChildren(skeleton("row", 2));
  try {
    renderScore(await Stocks.analysis(MARKET, TICKER, getPreset()));
  } catch (e) {
    $("#score").replaceChildren(errorState(e, loadScore));
  }
}

async function mountPresetControl() {
  presetList = await loadPresets();
  await mountPresetMenu($("#preset-menu"));
  document.addEventListener(PRESET_EVENT, loadScore);
}

function renderNumeric(a) {
  const m = a.metrics;
  const labels = ["1주", "1개월", "3개월", "6개월", "1년"];
  const data = [m.return_1w, m.return_1m, m.return_3m, m.return_6m, m.return_1y];
  const el = h(`<div class="numeric">
      <div class="chart-box chart-box--sm"><canvas role="img" aria-label="기간별 수익률 막대"></canvas></div>
      <div class="stat-grid">
        ${stat("연환산 변동성", pct(m.volatility_1y, { digits: 1 }), "최근 252거래일")}
        ${stat("최대낙폭(MDD)", pct(m.max_drawdown_1y, { digits: 1 }), "최근 252거래일")}
        ${stat("120일선 괴리율", pct(m.ma120_gap, { sign: true, digits: 1 }), m.ma120 ? `120일선 ${price(m.ma120, a.currency)}` : "")}
        ${stat("거래량/20일 평균", m.volume_ratio_20d !== null ? `${num(m.volume_ratio_20d, 2)}배` : DASH, `최신 ${num(m.volume)}주`)}
      </div></div>`);
  queueMicrotask(() => draw(el.querySelector("canvas"), {
    type: "bar",
    data: { labels, datasets: [{ data: data.map((x) => (x === null ? null : x * 100)), backgroundColor: data.map((x) => signColor(x, stock.country)), borderRadius: 10, maxBarThickness: 44 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: { x: plainAxis, y: { ...dashedAxis, ticks: { callback: (v) => `${v}%` } } },
      plugins: { tooltip: { callbacks: { label: (ctx) => (ctx.raw === null ? "데이터 부족" : `${ctx.raw > 0 ? "+" : ""}${ctx.raw.toFixed(2)}%`) } } },
    },
  }));
  $("#numeric").replaceChildren(el);
}

async function loadAnalysis() {
  for (const id of ["#key-metrics", "#score", "#numeric"]) $(id).replaceChildren(skeleton("row", 2));
  try {
    const a = await Stocks.analysis(MARKET, TICKER, getPreset());
    renderKeyMetrics(a);
    renderScore(a);
    renderNumeric(a);
  } catch (e) {
    for (const id of ["#key-metrics", "#score", "#numeric"]) $(id).replaceChildren(errorState(e, loadAnalysis));
  }
}

// ---------------------------------------------------------------- 재무 추이
function loadFinancials() {
  return load($("#financials"), {
    skeleton: h('<div class="skeleton" style="height:220px"></div>'),
    fetch: () => Stocks.financials(MARKET, TICKER),
    isEmpty: (d) => !d.items.length,
    empty: emptyState({ title: "재무 데이터가 없습니다" }),
    render: (d) => {
      const el = h(`<div class="section"><div class="legend"><span><i style="background:${color("--ice")}"></i>매출</span>
          <span><i style="background:${color("--lavender")}"></i>영업이익</span></div>
        <div class="chart-box chart-box--sm"><canvas role="img" aria-label="연간 매출·영업이익 막대"></canvas></div>
        <p class="subtle">FY 기준 · ${esc(d.items.at(-1).accounting_std || "")} · 출처 ${[...new Set(d.items.map((x) => x.data_source))].join(", ")} · 단위 ${d.currency}</p></div>`);
      queueMicrotask(() => draw(el.querySelector("canvas"), {
        type: "bar",
        data: {
          labels: d.items.map((x) => `FY${x.period_end.slice(0, 4)}`),
          datasets: [
            { label: "매출", data: d.items.map((x) => x.revenue), backgroundColor: color("--ice"), borderRadius: 10, maxBarThickness: 36 },
            { label: "영업이익", data: d.items.map((x) => x.operating_income), backgroundColor: color("--lavender"), borderRadius: 10, maxBarThickness: 36 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { x: plainAxis, y: { ...dashedAxis, ticks: { callback: (v) => money(v, d.currency) } } },
          plugins: { tooltip: { callbacks: {
            label: (ctx) => `${ctx.dataset.label} ${ctx.raw === null ? "없음" : money(ctx.raw, d.currency)}`,
            afterBody: (items) => { const r = d.items[items[0].dataIndex]; return r.operating_margin !== null ? `영업이익률 ${pct(r.operating_margin)}` : ""; },
          } } },
        },
      }));
      return el;
    },
  });
}

// ---------------------------------------------------------------- 경쟁 비교
const PEER_COLS = [
  { key: "return_1m", label: "1개월", fmt: (v) => pct(v, { sign: true, digits: 1 }) },
  { key: "return_3m", label: "3개월", fmt: (v) => pct(v, { sign: true, digits: 1 }) },
  { key: "return_1y", label: "1년", fmt: (v) => pct(v, { sign: true, digits: 1 }) },
  { key: "per", label: "PER", fmt: (v) => (v === null ? DASH : `${num(v, 1)}배`) },
  { key: "pbr", label: "PBR", fmt: (v) => (v === null ? DASH : `${num(v, 2)}배`) },
  { key: "roe", label: "ROE", fmt: (v) => pct(v, { digits: 1 }) },
  { key: "operating_margin", label: "영업이익률", fmt: (v) => pct(v, { digits: 1 }) },
  { key: "revenue_yoy", label: "매출 YoY", fmt: (v) => pct(v, { sign: true, digits: 1 }) },
  { key: "market_cap_krw", label: "시총(원화)", fmt: (v) => krw(v, { compact: true }) },
  { key: "score", label: "매력도(균형)", fmt: (v) => (v === null ? DASH : num(v, 0)) },
];
// 경쟁 비교 선 색: 대상 종목은 라벤더 굵은 선, 나머지는 등락 의미가 없는 구분색
const TARGET_COLOR = "#e6ddf2";
const PEER_COLORS = ["#5ea8ff", "#f5c26b", "#4fd1c5", "#f0a6ca", "#9ccc65", "#b39ddb"];
let peers = null, groupId = null, peerRange = "3m", peerMetric = "return_3m";

function peerTable(g) {
  const rows = g.members.map((m) => `<tr class="${m.is_target ? "is-target" : ""}">
      <td><a href="${stockUrl(m.market, m.ticker)}"><strong>${esc(m.name)}</strong></a> <span class="subtle">${esc(m.ticker)}</span></td>
      ${PEER_COLS.map((c) => `<td class="num">${c.fmt(m.values[c.key])}${m.ranks[c.key] ? `<span class="rk">${m.ranks[c.key]}위</span>` : ""}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table class="table">
      <caption class="sr-only">${esc(g.name)} 그룹 지표 비교 (순위는 그룹 내)</caption>
      <thead><tr><th scope="col">종목</th>${PEER_COLS.map((c) => `<th scope="col">${c.label}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td>그룹 평균</td>${PEER_COLS.map((c) => `<td class="num">${c.fmt(g.averages[c.key])}</td>`).join("")}</tr></tfoot>
    </table></div>`;
}

function drawPeerBars(canvas, g) {
  const col = PEER_COLS.find((c) => c.key === peerMetric);
  const isRatio = !["per", "pbr", "market_cap_krw", "score"].includes(peerMetric);
  const val = (m) => { const v = m.values[peerMetric]; return v === null ? null : isRatio ? v * 100 : v; };
  draw(canvas, {
    type: "bar",
    data: { labels: g.members.map((m) => m.name), datasets: [{
      data: g.members.map(val),
      backgroundColor: g.members.map((m) => (m.is_target ? color("--lavender") : color("--ice"))), borderRadius: 10, maxBarThickness: 40 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: { x: plainAxis, y: { ...dashedAxis, ticks: { callback: (v) => (peerMetric === "market_cap_krw" ? krw(v, { compact: true, unit: false }) : isRatio ? `${v}%` : v) } } },
      plugins: { tooltip: { callbacks: { label: (ctx) => `${col.label} ${col.fmt(g.members[ctx.dataIndex].values[peerMetric])}` } } },
    },
  });
}

async function drawPeerChart(box) {
  box.replaceChildren(h('<div class="skeleton" style="height:240px"></div>'));
  try {
    const d = await Stocks.peersChart(MARKET, TICKER, peerRange, groupId);
    let k = 0;
    const lineColor = d.series.map((s) => (s.is_target ? TARGET_COLOR : PEER_COLORS[k++ % PEER_COLORS.length]));
    const el = h(`<div><div class="legend">${d.series.map((s, i) => `<span><i style="background:${lineColor[i]}"></i>${esc(s.name)}${s.is_target ? " (현재)" : ""}</span>`).join("")}</div>
      <div class="chart-box chart-box--sm"><canvas role="img" aria-label="기준일 100 환산 가격 추이"></canvas></div><p class="subtle">${esc(d.note)}</p></div>`);
    box.replaceChildren(el);
    draw(el.querySelector("canvas"), {
      type: "line",
      data: { labels: d.dates, datasets: d.series.map((s, i) => ({
        label: s.name, data: s.values, borderColor: lineColor[i],
        borderWidth: s.is_target ? 3 : 1.5, pointRadius: 0, tension: 0.2, spanGaps: true })) },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: { ...plainAxis, ticks: { maxTicksLimit: 6, maxRotation: 0 } }, y: dashedAxis },
        plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label} ${ctx.raw === null ? "휴장" : num(ctx.raw, 1)}` } } },
      },
    });
  } catch (e) {
    box.replaceChildren(errorState(e, () => drawPeerChart(box)));
  }
}

function renderPeers() {
  const g = peers.groups.find((x) => x.group_id === groupId);
  const wrap = h('<div class="section"></div>');
  if (peers.groups.length > 1) {
    wrap.append(segmented(peers.groups.map((x) => ({ value: x.group_id, label: x.name })), groupId,
      (v) => { groupId = v; $("#peers").replaceChildren(renderPeers()); }, { label: "경쟁 그룹" }));
  }
  if (!g.has_peers) {
    wrap.append(emptyState({ title: g.message, body: `${esc(g.name)} 그룹에는 이 종목만 있습니다.` }));
    return wrap;
  }
  const chartBox = h("<div></div>");
  const rangeTabs = segmented(["1m", "3m", "6m", "1y"].map((v) => ({ value: v, label: v.toUpperCase() })), peerRange,
    (v) => { peerRange = v; drawPeerChart(chartBox); }, { label: "비교 차트 기간", variant: "segmented--card" });
  const metricSel = h(`<label class="metric-select"><span class="sr-only">비교 지표</span><select class="select">
      ${PEER_COLS.map((c) => `<option value="${c.key}" ${c.key === peerMetric ? "selected" : ""}>${c.label}</option>`).join("")}</select></label>`);
  const barBox = h('<div class="chart-box chart-box--sm"><canvas role="img" aria-label="선택 지표 막대 비교"></canvas></div>');
  const barCanvas = barBox.querySelector("canvas");
  metricSel.querySelector("select").addEventListener("change", (e) => { peerMetric = e.target.value; drawPeerBars(barCanvas, g); });
  wrap.append(
    h(`<div class="section__head"><h3>기준일 = 100 가격 추이</h3></div>`), rangeTabs, chartBox,
    h(`<div class="section__head"><h3>지표 비교 <span class="subtle">(그룹 내 순위 · 평균)</span></h3></div>`), h(peerTable(g)),
    h(`<div class="section__head"><h3>지표별 막대 비교</h3></div>`), metricSel, barBox,
    h(`<p class="notice">${esc(peers.accounting_note)} ${esc(peers.rank_rule)}</p>`),
  );
  queueMicrotask(() => { drawPeerChart(chartBox); drawPeerBars(barCanvas, g); });
  return wrap;
}

function loadPeers() {
  return load($("#peers"), {
    skeleton: skeleton("row", 3),
    fetch: () => Stocks.peers(MARKET, TICKER),
    isEmpty: (d) => !d.groups.length,
    empty: emptyState({ title: "속한 경쟁 그룹이 없습니다" }),
    render: (d) => {
      peers = d;
      groupId = d.groups.find((g) => g.has_peers)?.group_id ?? d.groups[0].group_id;
      return renderPeers();
    },
  });
}

// ---------------------------------------------------------------- 공시
function loadDisclosures() {
  return load($("#disclosures"), {
    skeleton: skeleton("row", 5),
    fetch: () => Stocks.disclosures(MARKET, TICKER),
    isEmpty: (d) => !d.items.length,
    empty: emptyState({ title: "최근 공시가 없습니다" }),
    render: (d) => {
      const ul = h('<ul class="list card card--flush"></ul>');
      ul.append(...d.items.map((x) => h(`<li><a class="row" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">
          <span class="avatar" aria-hidden="true">${x.data_source === "DART" ? "D" : "S"}</span>
          <span class="row__main"><span class="row__title">${esc(x.title)}</span>
            <span class="row__sub">${esc(x.report_type || "")} · ${x.data_source} <span class="sr-only">(새 창)</span></span></span>
          <span class="row__value subtle num">${date(x.filed_at)}</span></a></li>`)));
      return ul;
    },
  });
}

// ---------------------------------------------------------------- 시작
async function init() {
  $("#head").replaceChildren(h('<div class="skeleton" style="height:120px"></div>'));
  try {
    stock = await Stocks.detail(MARKET, TICKER);
  } catch (e) {
    $("#head").replaceChildren(e.status === 404
      ? emptyState({ title: "종목을 찾을 수 없습니다", body: `${esc(MARKET)}/${esc(TICKER)}`, action: '<a class="btn btn--primary" href="/stocks">주식 리스트로</a>' })
      : errorState(e, init));
    document.querySelectorAll(".detail-section").forEach((s) => (s.hidden = true));
    return;
  }
  renderHeader(stock);
  renderDetailNotice(stock.detail_status);
  loadCandles();
  if (!presetList) await mountPresetControl();
  loadAnalysis();
  loadFinancials();
  loadPeers();
  loadDisclosures();
  if (stock.detail_status === "loading") waitForDetail();
}

// ---------------------------------------------------------------- 비교군 종목 상세 데이터 (요청 시 수집)
const DETAIL_NOTICE = {
  loading: "매력도 비교군 종목이라 공시·2년 시세·5개년 재무를 지금 불러오는 중입니다. 받는 대로 화면이 갱신됩니다.",
  failed: "공시·재무 상세를 불러오지 못했습니다. 잠시 뒤 다시 열면 다시 시도합니다.",
};

function renderDetailNotice(status) {
  const old = $("#detail-notice");
  if (!DETAIL_NOTICE[status]) { old?.remove(); return; }
  const el = h(`<p class="notice ${status === "failed" ? "notice--warn" : ""}" id="detail-notice" role="status">${DETAIL_NOTICE[status]}</p>`);
  if (old) old.replaceWith(el); else $("#head").after(el);
}

let detailPoll = 0;
async function waitForDetail() {
  const token = ++detailPoll;
  for (let i = 0; i < 30 && token === detailPoll; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    let d;
    try { d = await Stocks.detail(MARKET, TICKER); } catch { continue; }
    if (d.detail_status === "loading") continue;
    renderDetailNotice(d.detail_status);
    if (d.detail_status === "ready") { loadCandles(); loadFinancials(); loadPeers(); loadDisclosures(); }
    return;
  }
}
document.addEventListener(REFRESHED_EVENT, init);
init();
