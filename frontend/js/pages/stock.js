// 종목 상세: 헤더·가격 차트·투자 매력도·핵심 정보 / 접힌 섹션(투자 지표 상세·재무 추이·월별 요약·경쟁 비교) / 최근 공시
import { PRESET_EVENT, Stats, Stocks, getPreset } from "../api.js";
import { DASH, changeHtml, date, esc, krw, num, pct, price, stockUrl, usd, volume } from "../format.js";
import { openAddToPortfolio } from "../components/add-to-portfolio.js";
import { loadPresets, mountPresetMenu } from "../components/preset-menu.js";
import { color, dashedAxis, draw, plainAxis } from "../components/charts.js";
import { icons } from "../components/icons.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";
import { emptyState, errorState, h, load, marketBadge, scoreBand, segmented, skeleton } from "../components/ui.js";
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
  document.title = `${s.name} (${s.ticker}) · StockMind`;
  const el = h(`<header class="stock-head">
      <div class="stock-head__id">
        <p class="subtle">${esc(s.ticker)} ${marketBadge(s.market, s.country)} ${s.groups.map((g) => `<span class="badge badge--market">${esc(g.name)}</span>`).join(" ")}
          ${s.sector ? `<span class="badge badge--sector" title="매력도 비교 업종${s.industry ? ` · ${esc(s.industry)}` : ""}">업종 ${esc(s.sector)}</span>` : ""}</p>
        <h1>${esc(s.name)}</h1>
        ${s.name_en && s.name_en !== s.name ? `<p class="subtle">${esc(s.name_en)}</p>` : ""}
      </div>
      <div class="stock-head__price">
        ${s.close === null ? '<p class="subtle">가격을 불러오는 중입니다</p>' : `
        <p class="stock-head__value num">${price(s.close, s.currency)}</p>
        <p>${changeHtml(s.change_rate, s.country)} <span class="subtle">${s.change !== null ? `(${s.change > 0 ? "+" : ""}${s.currency === "USD" ? usd(s.change) : krw(s.change)})` : ""}</span></p>
        ${s.currency === "USD" ? `<p class="subtle num">≈ ${krw(s.close_krw)} · 환율 ${num(s.fx_rate, 2)}${s.fx_stale ? " (지연)" : ""}</p>` : ""}
        <p class="subtle">일봉 기준 · ${date(s.as_of)} 종가</p>`}
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

// ---------------------------------------------------------------- 분석 (투자 매력도·핵심 정보·투자 지표 상세)
const stat = (label, value, sub = "") => `<div class="stat"><span class="stat__label">${label}</span>
  <span class="stat__value num">${value}</span>${sub ? `<span class="stat__sub">${sub}</span>` : ""}</div>`;
let analysisData = null;                 // 접힌 '투자 지표 상세'를 펼칠 때 다시 쓴다

function dividendStat(m, currency) {
  if (m.dps === null || m.dps === undefined) return stat("배당수익률", DASH, "배당 정보 없음");
  if (Number(m.dps) === 0) return stat("배당수익률", "무배당", "최근 1년 배당 없음");
  return stat("배당수익률", pct(m.dividend_yield, { digits: 2 }), `주당 ${price(m.dps, currency)} · 최신 종가 기준`);
}

function renderKeyMetrics(a) {
  const m = a.metrics;
  const pos = m.position_52w;
  const el = h(`<div class="stat-grid">
      ${stat("시가총액", money(m.market_cap, a.currency), a.currency === "USD" ? `≈ ${krw(m.market_cap_krw, { compact: true })}` : "")}
      ${dividendStat(m, a.currency)}
      <div class="stat stat--wide"><span class="stat__label">52주 범위 (일중 고저)</span>
        <span class="stat__value num" style="font-size:var(--fs-md)">${price(m.low_52w, a.currency)} – ${price(m.high_52w, a.currency)}</span>
        ${pos !== null ? `<div class="range" role="img" aria-label="52주 범위 내 위치 ${pct(pos, { digits: 0 })}"><span class="range__dot" style="left:${(pos * 100).toFixed(1)}%"></span></div>
          <span class="stat__sub">범위 내 위치 ${pct(pos, { digits: 0 })}</span>` : '<span class="stat__sub">1년 시세 부족</span>'}</div>
    </div>`);
  $("#key-metrics").replaceChildren(el);
}

function renderDetailMetrics(a) {
  const m = a.metrics;
  $("#detail-metrics").replaceChildren(h(`<div class="stat-grid">
      ${stat("PER", m.per ? `${num(m.per, 2)}배` : DASH, m.per ? "주가 ÷ 주당순이익" : "적자·미제공")}
      ${stat("PBR", m.pbr ? `${num(m.pbr, 2)}배` : DASH, "주가 ÷ 주당순자산")}
      ${stat("ROE", pct(m.roe), a.fin_period_end ? `FY ${a.fin_period_end.slice(0, 4)} · ${esc(a.accounting_std || "")}` : "재무 없음")}
      ${stat("영업이익률", pct(m.operating_margin), "영업이익 ÷ 매출")}
    </div>`));
  renderNumeric(a);
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

// 매력도 5요소 — 화면 이름은 일상어로(내부 키는 그대로). 레이더 축·요소 카드·계산 근거 표가 같은 이름을 쓴다
const FACTORS = [
  { key: "value", label: "저평가", desc: "버는 돈·가진 자산에 비해 주가가 싼 편인가" },
  { key: "quality", label: "수익성", desc: "자본과 매출로 돈을 잘 버는가 (ROE·영업이익률)" },
  { key: "growth", label: "성장성", desc: "매출과 이익이 작년보다 늘었나" },
  { key: "safety", label: "안정성", desc: "빚이 적고 주가 출렁임이 작은가" },
  { key: "momentum", label: "주가 흐름", desc: "최근 1년 주가가 오르는 추세인가" },
];
const FACTOR_LABEL = Object.fromEntries(FACTORS.map((f) => [f.key, f.label]));
const SIGNED_METRICS = ["revenue_yoy", "eps_change_yield", "momentum"];
const rawFmt = (m) => (m.raw_value === null ? DASH
  : m.metric === "debt_ratio" ? `${num(m.raw_value, 2)}배`
  : pct(m.raw_value, { digits: 1, sign: SIGNED_METRICS.includes(m.metric) }));
const zFmt = (v) => {
  if (v === null || v === undefined) return DASH;
  const r = Math.round(v * 100) / 100;
  return r === 0 ? "0.00" : `${r > 0 ? "+" : ""}${num(r, 2)}`;
};
// 팩터 점수(Z) → 같은 시장 안 위치 0~100 (50 = 시장 중앙). 종합 점수와 같은 100·Φ(z) 변환
const erf = (x) => {   // Abramowitz-Stegun 7.1.26 (오차 1.5e-7)
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
};
const toPos = (z) => (z === null || z === undefined ? null : 100 * 0.5 * (1 + erf(z / Math.SQRT2)));
// 요소별 '날씨': 같은 시장 안 위치 60 이상 맑음(강함) · 40~60 구름(보통) · 40 미만 비(약함)
const WEATHER = [
  { min: 60, icon: icons.sun, word: "강함", cls: "wx--sun" },
  { min: 40, icon: icons.cloudSun, word: "보통", cls: "wx--cloud" },
  { min: -Infinity, icon: icons.rain, word: "약함", cls: "wx--rain" },
];
const weather = (p) => WEATHER.find((w) => p >= w.min);
// 받침 유무에 따른 조사 (이/가, 은/는)
const hasBatchim = (word) => { const c = word.charCodeAt(word.length - 1) - 0xac00; return c >= 0 && c <= 11171 && c % 28 !== 0; };
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

/** 강한 요소·약한 요소를 한 문장으로 */
function summarySentence(pos) {
  const known = FACTORS.filter((f) => pos[f.key] !== null);
  if (known.length < 3) return "비교할 수 있는 요소가 적어 요약하지 않습니다.";
  const strong = known.filter((f) => pos[f.key] >= 60).sort((a, b) => pos[b.key] - pos[a.key]).map((f) => f.label);
  const weak = known.filter((f) => pos[f.key] < 40).sort((a, b) => pos[a.key] - pos[b.key]).map((f) => f.label);
  if (!strong.length && !weak.length) return "같은 시장 비교군과 비교하면 다섯 요소 모두 중간 수준입니다.";
  const parts = [];
  if (strong.length) parts.push(`<strong>${strong.join("·")}</strong>${hasBatchim(strong.at(-1)) ? "이" : "가"} 강한 편`);
  if (weak.length) parts.push(`<strong>${weak.join("·")}</strong>${hasBatchim(weak.at(-1)) ? "은" : "는"} 약한 편`);
  return `같은 시장 비교군과 비교하면 ${parts.join("이고, ")}입니다.`;
}

function drawRadar(canvas, pos, peer) {
  const datasets = [{
    label: "이 종목", data: FACTORS.map((f) => pos[f.key]), borderColor: color("--lavender"), backgroundColor: "rgba(230,221,242,.22)",
    borderWidth: 2, pointRadius: 3, pointBackgroundColor: color("--lavender"), spanGaps: true,
  }];
  if (peer) {
    datasets.push({
      label: `${peer.group_name} 평균`, data: FACTORS.map((f) => toPos(peer.factors[f.key])), borderColor: color("--ice"),
      backgroundColor: "transparent", borderWidth: 1.5, borderDash: [5, 4], pointRadius: 2, pointBackgroundColor: color("--ice"), spanGaps: true,
    });
  }
  datasets.push({
    label: "시장 중앙", data: FACTORS.map(() => 50), borderColor: color("--text-3"), backgroundColor: "transparent",
    borderWidth: 1, borderDash: [2, 4], pointRadius: 0,
  });
  draw(canvas, {
    type: "radar",
    data: { labels: FACTORS.map((f) => f.label), datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: color("--line") },
        angleLines: { color: color("--line") }, pointLabels: { color: color("--text-2"), font: { size: 12, weight: "600" } } } },
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label} ${ctx.raw === null ? "데이터 없음" : Math.round(ctx.raw)}` } } },
    },
  });
}

function renderScore(a) {
  const s = a.attractiveness;
  if (!s.as_of) {
    $("#score").replaceChildren(emptyState({
      title: s.reference ? "참고 매력도를 계산할 수 없습니다" : "매력도가 아직 계산되지 않았습니다",
      body: s.reference ? "비교군 점수가 아직 없거나 이 종목 시세가 부족합니다." : "사이드바의 새로고침으로 점수를 계산할 수 있습니다." }));
    return;
  }
  const dq = s.data_quality || {};
  const market = s.rank?.country === "US" ? "미국" : "국내";
  const factors = Object.entries(s.factors);
  const pos = Object.fromEntries(FACTORS.map((f) => [f.key, s.factors[f.key]?.available ? toPos(s.factors[f.key].score) : null]));
  const band = scoreBand(s.score);
  const rankText = !s.rank ? "순위 없음"
    : s.reference ? `${market} 비교군 ${s.rank.total - 1}개 사이에 넣으면 약 <strong>${s.rank.position}위</strong>`
    : `${market} 비교군 ${s.rank.total}개 중 <strong>${s.rank.position}위</strong>`;
  const el = h(`<div class="score-panel">
      <div class="score-panel__gauge">${gauge(s.score)}
        ${band ? `<p class="score-band"><i style="background:var(--gauge-${band.index})"></i>${band.label}</p>` : ""}
        ${s.reference ? '<span class="badge badge--market">참고 점수</span>' : ""}
        <p class="score-panel__rank">${rankText}</p>
        <p class="subtle">${esc(s.preset.name)} 성향 · ${date(s.as_of)} 기준</p></div>
      <div class="score-panel__radar">
        <div class="chart-box chart-box--radar"><canvas role="img" aria-label="매력도 5요소 레이더 (같은 시장 안 위치 0~100, 50 = 시장 중앙)"></canvas></div>
        <div class="legend"><span><i style="background:${color("--lavender")}"></i>이 종목</span>
          ${s.peer_average ? `<span><i style="background:${color("--ice")}"></i>${esc(s.peer_average.group_name)} 평균 (${s.peer_average.size}종목)</span>` : ""}
          <span><i style="background:${color("--text-3")}"></i>시장 중앙 50</span></div>
      </div>
      <p class="score-summary">${summarySentence(pos)}</p>
      <ul class="wx-list" aria-label="요소별 강약">${FACTORS.map((f) => {
        const p = pos[f.key];
        const w = p === null ? null : weather(p);
        return `<li class="wx ${w ? w.cls : "wx--na"}">
            <span class="wx__icon" aria-hidden="true">${w ? w.icon : icons.alert}</span>
            <span class="wx__body"><span class="wx__head"><strong>${f.label}</strong>
              <span class="wx__word">${w ? `${w.word} <span class="num">${Math.round(p)}</span>` : "데이터 없음"}</span></span>
              <span class="wx__desc">${f.desc}</span></span></li>`;
      }).join("")}</ul>
    </div>`);
  if (s.reference && s.reference_note) el.append(h(`<p class="notice">${esc(s.reference_note)}</p>`));

  // 계산 근거(팩터 기여도·지표 원값/Z·메모·방법)는 접어 둔다
  const maxAbs = Math.max(0.5, ...factors.map(([, f]) => Math.abs(f.contribution ?? 0)));
  const notes = [dq.score_null_reason, ...(dq.notes || [])].filter(Boolean);
  const basis = h(`<details class="score-method"><summary>계산 근거 보기 <span class="subtle">팩터 기여도 · 지표 원값과 표준점수(Z)</span></summary>
      <div class="score-basis">
        <p class="subtle">데이터 충족도 ${s.factor_coverage}/${s.factor_total} 요소${s.rank ? ` · 백분위 ${num(s.rank.percentile, 0)}` : ""}</p>
        <div class="score-panel__factors">
          <h3>팩터 기여도 <span class="subtle">(유효 팩터 가중치 × 팩터 점수, 합 = 종합 ${zFmt(s.composite)})</span></h3>
          ${factors.map(([k, f]) => contribRow(k, f, maxAbs)).join("")}
          <p class="subtle">팩터 점수는 같은 시장 안 표준점수(Z) 단위입니다. 0이 시장 중앙, 음수 기여는 왼쪽으로 표시합니다.
            레이더·요소 카드의 0~100은 이 Z를 100·Φ(Z)로 바꾼 값입니다.</p>
        </div>
      </div></details>`);
  const body = basis.querySelector(".score-basis");
  const rows = s.metrics.map((m) => `<tr title="${esc(dq.missing_metrics?.[m.metric] || "")}">
      <td>${esc(m.label)}${m.direction < 0 ? ' <span class="subtle">낮을수록 좋음</span>' : ""}</td>
      <td>${FACTOR_LABEL[m.factor]}</td><td class="num">${rawFmt(m)}</td>
      <td class="num">${zFmt(m.z_raw)}</td><td class="num">${zFmt(m.z_adj)}</td></tr>`).join("");
  body.append(h(`<div class="table-wrap"><table class="table table--metrics">
      <caption class="sr-only">매력도 지표별 원값과 표준점수</caption>
      <thead><tr><th scope="col">지표</th><th scope="col">요소</th><th scope="col">원값</th><th scope="col">Z (시장 내)</th><th scope="col">Z (섹터 중립)</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`));
  if (notes.length || dq.missing_metrics) {
    const missing = Object.entries(dq.missing_metrics || {}).map(([k, v]) => `${esc(s.metrics.find((m) => m.metric === k)?.label || k)}: ${esc(v)}`);
    body.append(h(`<ul class="score-notes">${[...notes.map(esc), ...missing].map((t) => `<li>${t}</li>`).join("")}</ul>`));
  }
  body.append(h(`<div><h3>계산 방법</h3><p class="subtle">${esc(s.method)}</p>
      <p class="subtle">${esc(s.preset.description || "")} — ${esc(presetList?.note || "")}</p></div>`));
  el.append(basis, h(`<p class="subtle">${esc(a.disclaimer)}</p>`));
  $("#score").replaceChildren(el);
  queueMicrotask(() => drawRadar(el.querySelector(".chart-box--radar canvas"), pos, s.peer_average));
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
      <h3>기간 수익률과 위험</h3>
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
  for (const id of ["#key-metrics", "#score"]) $(id).replaceChildren(skeleton("row", 2));
  try {
    analysisData = await Stocks.analysis(MARKET, TICKER, getPreset());
    renderKeyMetrics(analysisData);
    renderScore(analysisData);
  } catch (e) {
    analysisData = null;
    for (const id of ["#key-metrics", "#score"]) $(id).replaceChildren(errorState(e, loadAnalysis));
  }
  reloadFold("metrics");
}

// ---------------------------------------------------------------- 접힌 섹션: 처음 펼칠 때 불러온다
const folds = {};
function fold(name, loader) {
  const el = $(`#fold-${name}`);
  const f = folds[name] = { el, loader, loaded: false };
  el.addEventListener("toggle", () => {
    if (el.open && !f.loaded && stock) { f.loaded = true; loader(); }
  });
}
/** 데이터가 바뀌었을 때: 펼쳐져 있으면 지금 다시, 접혀 있으면 다음에 펼칠 때 */
function reloadFold(name) {
  const f = folds[name];
  if (f.el.open && stock) { f.loaded = true; f.loader(); } else f.loaded = false;
}

// ---------------------------------------------------------------- 재무 추이
// ---------------------------------------------------------------- 월별 요약 (GET /statistics/monthly)
function loadMonthly() {
  return load($("#monthly"), {
    skeleton: skeleton("row", 3),
    fetch: () => Stats.monthly(MARKET, TICKER, 12),
    isEmpty: (d) => !d.items.length,
    empty: emptyState({ title: "월별로 집계할 시세가 없습니다" }),
    render: (d) => {
      const rows = [...d.items].reverse().map((m) => `<tr>
          <td>${esc(m.month)}${m.is_partial ? ' <span class="badge badge--market">진행 중</span>' : ""}</td>
          <td class="num">${m.trading_days}</td>
          <td class="num">${price(m.avg_close, d.currency)}</td>
          <td class="num">${price(m.max_high, d.currency)}</td>
          <td class="num">${price(m.min_low, d.currency)}</td>
          <td class="num">${changeHtml(m.monthly_return, stock.country)}</td>
          <td class="num">${volume(m.total_volume)}</td></tr>`).join("");
      return h(`<div class="section"><div class="table-wrap"><table class="table">
          <caption class="sr-only">월별 거래일 수, 평균 종가, 최고가, 최저가, 월간 수익률, 거래량 합계</caption>
          <thead><tr><th scope="col">월</th><th scope="col">거래일</th><th scope="col">평균 종가</th><th scope="col">최고</th>
            <th scope="col">최저</th><th scope="col">월간 수익률</th><th scope="col">거래량</th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <p class="subtle">월간 수익률 = 그 달 첫 거래일 종가 대비 마지막 거래일 종가 · 단위 ${esc(d.currency)} · 진행 중인 달은 마지막 거래일까지</p></div>`);
    },
  });
}

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
fold("metrics", () => {
  if (analysisData) renderDetailMetrics(analysisData);
  else $("#detail-metrics").replaceChildren(emptyState({ title: "지표를 아직 불러오지 못했습니다" }));
});
fold("financials", loadFinancials);
fold("monthly", loadMonthly);
fold("peers", loadPeers);

const hasPrices = (s) => s.as_of !== null && s.as_of !== undefined;

/** 시세가 있어야 의미 있는 영역: 가격 차트·투자 매력도·핵심 정보와 펼쳐 둔 섹션 */
function loadPriced() {
  loadCandles();
  loadAnalysis();
  for (const name of ["financials", "monthly", "peers"]) reloadFold(name);
}

function showWaiting() {
  $("#price-chart").replaceChildren(h('<div class="skeleton" style="height:280px" aria-busy="true" aria-label="가격 불러오는 중"></div>'));
  for (const id of ["#score", "#key-metrics"]) $(id).replaceChildren(skeleton("row", 2));
}

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
  renderDetailNotice(stock.detail_status, stock.coverage);
  if (!presetList) await mountPresetControl();
  const waiting = stock.detail_status === "loading" && !hasPrices(stock);
  if (waiting) showWaiting(); else loadPriced();
  if (stock.detail_status === "loading") $("#disclosures").replaceChildren(skeleton("row", 3));   // 받는 중에는 '없음' 대신 대기
  else loadDisclosures();
  if (stock.detail_status === "loading") waitForDetail(!waiting);
}

// ---------------------------------------------------------------- 비교군·상장 목록 종목 상세 데이터 (요청 시 수집)
const DETAIL_NOTICE = {
  loading: {
    benchmark: "매력도 비교군 종목이라 공시·2년 시세·5개년 재무를 지금 불러오는 중입니다. 받는 대로 화면이 갱신됩니다.",
    listed: "상장 종목 목록에서 찾은 종목이라 데이터를 지금 불러오고 있습니다. 가격 차트가 먼저 나오고, 매력도·재무·공시가 이어서 채워집니다(보통 10~30초).",
  },
  failed: "공시·재무 상세를 불러오지 못했습니다. 잠시 뒤 다시 열면 다시 시도합니다.",
};

function renderDetailNotice(status, coverage) {
  const old = $("#detail-notice");
  const text = status === "loading" ? DETAIL_NOTICE.loading[coverage] || DETAIL_NOTICE.loading.benchmark : DETAIL_NOTICE[status];
  if (!text) { old?.remove(); return; }
  const el = h(`<p class="notice ${status === "failed" ? "notice--warn" : ""}" id="detail-notice" role="status">${text}</p>`);
  if (old) old.replaceWith(el); else $("#head").after(el);
}

let detailPoll = 0;
/** 수집이 끝날 때까지 2초마다 확인. 일봉이 먼저 들어오면 가격 차트·매력도부터 그리고, 끝나면 전체를 다시 그린다 */
async function waitForDetail(pricesShown) {
  const token = ++detailPoll;
  for (let i = 0; i < 60 && token === detailPoll; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    let d;
    try { d = await Stocks.detail(MARKET, TICKER); } catch { continue; }
    if (token !== detailPoll) return;
    if (!pricesShown && hasPrices(d)) {
      pricesShown = true;
      stock = d;
      renderHeader(d);
      loadPriced();
    }
    if (d.detail_status === "loading") continue;
    stock = d;
    renderHeader(d);
    renderDetailNotice(d.detail_status, d.coverage);
    if (d.detail_status === "ready") { loadPriced(); loadDisclosures(); }
    return;
  }
}
document.addEventListener(REFRESHED_EVENT, init);
init();
