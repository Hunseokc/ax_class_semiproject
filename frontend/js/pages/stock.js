// 종목 상세: 헤더(이름·가격·등락) · 가격 차트(종가 선 + 거래량 막대) · 핵심 정보(시총·PER·PBR)
import { PRESET_EVENT, getAnalysis, getCandles, getDisclosures, getFinancials, getPreset, getStock } from "../api.js";   // [S4-A] PRESET_EVENT·getAnalysis·getPreset
import { DASH, changeHtml, date, esc, krw, num, pct, price, usd } from "../format.js";
import { color, dashedAxis, draw, plainAxis, scoreBand } from "../components/charts.js";   // [S4-A] scoreBand
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";   // [S3-A] REFRESHED_EVENT
import { emptyState, errorState, h, load, marketBadge, segmented, skeleton } from "../components/ui.js";
import { icons } from "../components/icons.js";   // [S2-A]
import { openAddToPortfolio } from "../components/add-to-portfolio.js";   // [S2-A]
import { starButton } from "../components/watch.js";   // [S2-A]
import { loadPresets, mountPresetMenu } from "../components/preset-menu.js";   // [S4-A]

mountSidebar("stocks");
const $ = (sel) => document.querySelector(sel);
const [, , MARKET, TICKER] = location.pathname.split("/").map(decodeURIComponent);   // /stocks/KOSPI/005930
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
        <p class="subtle">${esc(s.ticker)} ${marketBadge(s.market, s.country)} ${s.groups.map((g) => `<span class="badge badge--market">${esc(g.name)}</span>`).join(" ")}</p>
        <h1>${esc(s.name)}</h1>
        ${s.name_en && s.name_en !== s.name ? `<p class="subtle">${esc(s.name_en)}</p>` : ""}
      </div>
      <div class="stock-head__price">
        ${s.close === null ? '<p class="subtle">가격 정보가 없습니다</p>' : `
        <p class="stock-head__value num">${price(s.close, s.currency)}</p>
        <p>${changeHtml(s.change_rate, s.country)} <span class="subtle">${s.change !== null ? `(${s.change > 0 ? "+" : ""}${s.currency === "USD" ? usd(s.change) : krw(s.change)})` : ""}</span></p>
        ${s.currency === "USD" ? `<p class="subtle num">≈ ${krw(s.close_krw)} · 환율 ${num(s.fx_rate, 2)}${s.fx_stale ? " (지연)" : ""}</p>` : ""}
        <p class="subtle">일봉 기준 · ${date(s.as_of)} 종가</p>`}
      </div>
      <div class="stock-head__actions"></div>
    </header>`);
  const add = h(`<button class="btn btn--accent" type="button">${icons.plus}<span>포트폴리오에 담기</span></button>`);   // [S2-A]
  add.addEventListener("click", () => openAddToPortfolio(s));
  el.querySelector(".stock-head__actions").append(starButton(s, s.is_watched), add);
  $("#head").replaceChildren(el);
}

// ---------------------------------------------------------------- 가격 차트
let range = "3m";
function loadCandles() {
  return load($("#price-chart"), {
    skeleton: h('<div class="skeleton" style="height:280px"></div>'),
    fetch: () => getCandles(MARKET, TICKER, range),
    isEmpty: (d) => !d.candles.length,
    empty: emptyState({ title: "해당 기간의 시세가 없습니다" }),
    render: (d) => {
      const box = h('<div class="chart-box"><canvas role="img" aria-label="종가와 거래량 차트"></canvas></div>');
      const c = d.candles;
      const first = c[0].close, last = c.at(-1).close;
      const line = signColor(last - first, stock.country);          // 기간 수익이면 상승색, 손실이면 하락색
      queueMicrotask(() => draw(box.querySelector("canvas"), {      // canvas가 화면에 붙은 뒤에 그린다
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
            v: { display: false, max: Math.max(...c.map((x) => x.volume)) * 4 },   // 막대가 차트 아래쪽 1/4만 쓰도록
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

// ---------------------------------------------------------------- 핵심 정보 (시총·PER·PBR)
const stat = (label, value, sub = "") => `<div class="stat"><span class="stat__label">${label}</span>
  <span class="stat__value num">${value}</span>${sub ? `<span class="stat__sub">${sub}</span>` : ""}</div>`;

function renderKeyMetrics(s) {
  $("#key-metrics").replaceChildren(h(`<div class="stat-grid">
      ${stat("시가총액", money(s.market_cap, s.currency), s.currency === "USD" ? `≈ ${krw(s.market_cap_krw, { compact: true })}` : "")}
      ${stat("PER", s.per ? `${num(s.per, 2)}배` : DASH, s.per ? "주가 ÷ 주당순이익" : "적자·미제공")}
      ${stat("PBR", s.pbr ? `${num(s.pbr, 2)}배` : DASH, "주가 ÷ 주당순자산")}
    </div>`));
}

// ── [S3-A] 재무 추이 ──
// stock.html은 A의 담당 파일 목록에 없어서, 이 파일이 '재무 추이' 칸을 핵심 정보 바로 아래에 만들어 붙인다
const finSection = h(`<section class="section card detail-section" aria-labelledby="h-fin">
    <h2 id="h-fin">재무 추이</h2><div id="financials"></div></section>`);
$("#key-metrics").closest("section").after(finSection);

const FIN_COLORS = () => [color("--ice"), color("--lavender"), "#aba2fc"];   // 매출·영업이익·순이익 (세 번째는 구분색, 등락 의미 없음)
function loadFinancials() {
  return load($("#financials"), {
    skeleton: h('<div class="skeleton" style="height:220px"></div>'),
    fetch: () => getFinancials(MARKET, TICKER),
    isEmpty: (d) => !d.items.length,
    empty: emptyState({ title: "재무 데이터가 없습니다" }),
    render: (d) => {
      const items = [...d.items].sort((a, b) => a.period_end.localeCompare(b.period_end));   // 오래된 해가 왼쪽
      const cols = [["매출", "revenue"], ["영업이익", "operating_income"], ["순이익", "net_income"]];
      const colors = FIN_COLORS();
      const fy = (x) => `FY${x.period_end.slice(0, 4)}`;
      const cell = (v) => (v === null || v === undefined ? DASH : money(v, d.currency));      // 없음은 0이 아니라 '–'
      const el = h(`<div><div class="legend">${cols.map(([label], i) => `<span><i style="background:${colors[i]}"></i>${label}</span>`).join("")}</div>
        <div class="chart-box chart-box--sm"><canvas role="img" aria-label="연간 매출·영업이익·순이익 막대"></canvas></div>
        <div class="table-wrap"><table class="table">
          <caption class="sr-only">연도별 매출, 영업이익, 순이익, 영업이익률 (단위 ${esc(d.currency)})</caption>
          <thead><tr><th scope="col">항목</th>${items.map((x) => `<th scope="col">${fy(x)}</th>`).join("")}</tr></thead>
          <tbody>${cols.map(([label, key]) => `<tr><th scope="row">${label}</th>${items.map((x) => `<td class="num">${cell(x[key])}</td>`).join("")}</tr>`).join("")}
            <tr><th scope="row">영업이익률</th>${items.map((x) => `<td class="num">${x.operating_margin === null ? DASH : pct(x.operating_margin)}</td>`).join("")}</tr></tbody>
        </table></div>
        <p class="subtle">FY(연간) 기준 · ${esc(items.at(-1).accounting_std || "")} · 출처 ${[...new Set(items.map((x) => x.data_source))].join(", ")} · 단위 ${esc(d.currency)}</p></div>`);
      queueMicrotask(() => draw(el.querySelector("canvas"), {
        type: "bar",
        data: {
          labels: items.map(fy),
          datasets: cols.map(([label, key], i) => ({ label, data: items.map((x) => x[key]), backgroundColor: colors[i], borderRadius: 10, maxBarThickness: 36 })),
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { x: plainAxis, y: { ...dashedAxis, ticks: { callback: (v) => money(v, d.currency) } } },
          plugins: { tooltip: { callbacks: {
            label: (ctx) => `${ctx.dataset.label} ${ctx.raw === null ? "없음" : money(ctx.raw, d.currency)}`,
            afterBody: (tips) => { const r = items[tips[0].dataIndex]; return r.operating_margin !== null ? `영업이익률 ${pct(r.operating_margin)}` : ""; },
          } } },
        },
      }));
      return el;
    },
  });
}

// ── [S3-A] 최근 공시 ──
const discSection = h(`<section class="section detail-section" aria-labelledby="h-disc">
    <h2 id="h-disc">최근 공시</h2><div id="disclosures"></div></section>`);
finSection.after(discSection);

function loadDisclosures() {
  return load($("#disclosures"), {
    skeleton: skeleton("row", 5),
    fetch: () => getDisclosures(MARKET, TICKER),
    isEmpty: (d) => !d.items.length,
    empty: emptyState({ title: "최근 공시가 없습니다" }),
    render: (d) => {
      const ul = h('<ul class="list card card--flush"></ul>');
      ul.append(...d.items.map((x) => {
        const inner = `<span class="avatar" aria-hidden="true">${x.data_source === "DART" ? "D" : "S"}</span>
          <span class="row__main"><span class="row__title">${esc(x.title)}</span>
            <span class="row__sub">${esc(x.report_type || "")} · ${esc(x.data_source)}${x.url ? ' <span class="sr-only">(새 창)</span>' : ""}</span></span>
          <span class="row__value subtle num">${date(x.filed_at)}</span>`;
        return h(`<li>${x.url   // 원문 링크가 없으면 글자만 보여 준다
          ? `<a class="row" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${inner}</a>`
          : `<div class="row">${inner}</div>`}</li>`);
      }));
      return ul;
    },
  });
}

// ── [S4-A] 투자 매력도 ──
// stock.html은 A의 담당 파일 목록에 없어서, 이 파일이 '투자 매력도' 칸을 가격 차트 바로 아래에 만들어 붙인다
const scoreSection = h(`<section class="section card detail-section" aria-labelledby="h-score">
    <div class="section__head"><h2 id="h-score">투자 매력도</h2><div id="preset-menu"></div></div>
    <div id="score"></div></section>`);
$("#price-chart").closest("section").after(scoreSection);

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
      title: "매력도가 아직 계산되지 않았습니다",
      body: "사이드바의 새로고침으로 점수를 계산할 수 있습니다." }));
    return;
  }
  const dq = s.data_quality || {};
  const market = s.rank?.country === "US" ? "미국" : "국내";
  const factors = Object.entries(s.factors);
  const pos = Object.fromEntries(FACTORS.map((f) => [f.key, s.factors[f.key]?.available ? toPos(s.factors[f.key].score) : null]));
  const band = scoreBand(s.score);
  const rankText = !s.rank ? "순위 없음" : `${market} 비교군 ${s.rank.total}개 중 <strong>${s.rank.position}위</strong>`;
  const el = h(`<div class="score-panel">
      <div class="score-panel__gauge">${gauge(s.score)}
        ${band ? `<p class="score-band"><i style="background:var(--gauge-${band.index})"></i>${band.label}</p>` : ""}
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
  // 서버 문구가 비어도 '투자 권유가 아님'은 항상 보이게 고정 문구를 함께 둔다
  el.append(basis, h(`<p class="subtle">${esc(a.disclaimer || "")} 이 점수는 투자 권유가 아닙니다.</p>`));
  $("#score").replaceChildren(el);
  queueMicrotask(() => drawRadar(el.querySelector(".chart-box--radar canvas"), pos, s.peer_average));
}

// 분석 응답은 한 번만 받아 둔다 — 매력도(위)와 수치 분석이 같이 쓴다. 성향이 바뀌면 다시 받는다
let analysisData = null;
async function loadAnalysis() {
  $("#score").replaceChildren(skeleton("row", 2));
  try {
    analysisData = await getAnalysis(MARKET, TICKER, getPreset());
    renderScore(analysisData);
  } catch (e) {
    analysisData = null;
    $("#score").replaceChildren(errorState(e, loadAnalysis));
  }
  reloadFold("metrics");   // 수치 분석 칸이 펼쳐져 있으면 지금 다시, 접혀 있으면 다음에 펼칠 때
}

let presetMounted = false;   // init()이 새로고침마다 다시 돌아도 메뉴·이벤트 연결은 한 번만
async function mountPresetControl() {
  if (presetMounted) return;
  presetMounted = true;
  presetList = await loadPresets();
  await mountPresetMenu($("#preset-menu"));
  document.addEventListener(PRESET_EVENT, loadAnalysis);
}

// ── [S4-A] 수치 분석 (접힌 '투자 지표 상세') ──
// 복잡한 자료는 기본으로 접어 두고, 처음 펼칠 때 그린다. stock.html을 못 고쳐서 이 파일이 칸을 만들어 핵심 정보 바로 아래(재무 추이 위)에 붙인다
const foldMetrics = h(`<details class="section card detail-section fold" id="fold-metrics">
    <summary><h2>투자 지표 상세</h2><span class="subtle">ROE·영업이익률·기간 수익률·변동성·낙폭</span></summary>
    <div class="fold__body"><div id="detail-metrics"></div><div id="numeric"></div></div></details>`);
$("#key-metrics").closest("section").after(foldMetrics);

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

// PER·PBR은 위의 '핵심 정보'에 이미 있어서 여기서는 재무 기반 두 지표만 둔다
function renderDetailMetrics(a) {
  const m = a.metrics;
  $("#detail-metrics").replaceChildren(h(`<div class="stat-grid">
      ${stat("ROE", pct(m.roe), a.fin_period_end ? `FY ${a.fin_period_end.slice(0, 4)} · ${esc(a.accounting_std || "")}` : "재무 없음")}
      ${stat("영업이익률", pct(m.operating_margin), "영업이익 ÷ 매출")}
    </div>`));
  renderNumeric(a);
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

fold("metrics", () => {
  if (analysisData) renderDetailMetrics(analysisData);
  else $("#detail-metrics").replaceChildren(emptyState({ title: "지표를 아직 불러오지 못했습니다" }));
});

// ---------------------------------------------------------------- 시작
async function init() {
  $("#head").replaceChildren(h('<div class="skeleton" style="height:120px"></div>'));
  try {
    stock = await getStock(MARKET, TICKER);
  } catch (e) {
    $("#head").replaceChildren(e.status === 404
      ? emptyState({ title: "종목을 찾을 수 없습니다", body: `${esc(MARKET)}/${esc(TICKER)}`, action: '<a class="btn btn--primary" href="/stocks">주식 리스트로</a>' })
      : errorState(e, init));
    document.querySelectorAll(".detail-section").forEach((s) => (s.hidden = true));
    return;
  }
  document.querySelectorAll(".detail-section").forEach((s) => (s.hidden = false));   // 다시 시도 성공 시 복구
  renderHeader(stock);
  renderKeyMetrics(stock);
  loadCandles();
  loadFinancials();   // [S3-A]
  loadDisclosures();  // [S3-A]
  mountPresetControl();   // [S4-A] 성향 메뉴(한 번만)
  loadAnalysis();         // [S4-A] 매력도
}
init();

// ── [S3-A] 사이드바 새로고침이 끝나면 상세 화면을 새 값으로 다시 불러온다 ──
document.addEventListener(REFRESHED_EVENT, init);
