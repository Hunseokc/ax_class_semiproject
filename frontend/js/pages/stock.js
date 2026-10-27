// 종목 상세: 헤더(이름·가격·등락) · 가격 차트(종가 선 + 거래량 막대) · 핵심 정보(시총·PER·PBR)
import { PRESET_EVENT, getAnalysis, getCandles, getDisclosures, getFinancials, getMonthly, getPeers, getPeersChart, getPreset, getStock } from "../api.js";   // [S4-A] PRESET_EVENT·getAnalysis·getPreset  [S5-A] getMonthly
import { DASH, changeHtml, date, esc, krw, num, pct, price, stockUrl, usd, volume } from "../format.js";   // [S4-A] stockUrl  [S5-A] volume
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
// 주 테마(점수 비교 기준)는 채운 배지, 보조 테마(함께 하는 사업)는 테두리 배지, 원자재 연동이면 경고 배지
function themeBadges(s) {
  const groups = s.groups.map((g) => g.is_primary
    ? `<span class="badge badge--market" title="주 테마 — 매력도를 이 테마 종목과 비교합니다">${esc(g.name)}</span>`
    : `<span class="badge badge--sector" title="함께 속한 테마">${esc(g.name)}</span>`);
  if (s.theme?.commodity_linked) {
    groups.push(`<span class="badge badge--commodity" title="원자재 가격을 따라 이익이 크게 바뀌는 업종">원자재 연동</span>`);
  }
  return groups.join(" ");
}

function renderHeader(s) {
  document.title = `${s.name} (${s.ticker}) · StockMind`;
  const el = h(`<header class="stock-head">
      <div class="stock-head__id">
        <p class="subtle">${esc(s.ticker)} ${marketBadge(s.market, s.country)} ${themeBadges(s)}</p>
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
            { type: "bar", label: "거래량", data: c.map((x) => x.volume), backgroundColor: color("--lavender-fill"), borderRadius: 4, yAxisID: "v", order: 2 },
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

// 경쟁 비교 응답은 핵심 정보(PER·PBR 비교)와 '경쟁 종목 비교' 칸이 같이 쓴다 — 한 번만 요청, 실패하면 다음에 다시
let peersReq = null;
const fetchPeers = () => (peersReq ??= getPeers(MARKET, TICKER).catch((e) => { peersReq = null; throw e; }));

/** 비교 그룹(경쟁 비교 칸과 같은 첫 그룹)의 다른 종목들 값 평균과 개수. 비교할 종목이 없으면 null
 *  positive: PER·PBR처럼 양수만 의미 있는 지표면 true(적자 음수 제외), ROE·영업이익률은 false */
function peerAverage(d, key, { positive = true } = {}) {
  const g = d.groups.find((x) => x.has_peers);
  const vals = (g?.members || []).filter((m) => !m.is_target).map((m) => m.values[key])
    .filter((v) => (positive ? v > 0 : typeof v === "number"));
  return vals.length ? { avg: vals.reduce((a, b) => a + b, 0) / vals.length, n: vals.length } : null;
}

// PER·PBR: 경쟁 종목 평균 대비 몇 % 낮은지/높은지를 크게, 원래 수치는 옆 괄호에 작게. 비교할 수 없으면 원래 수치만
function valuationStat(label, v, cmp, rawSub) {
  if (!(v > 0)) return stat(label, DASH, label === "PER" ? "적자·미제공" : "미제공");
  const raw = `${num(v, 2)}배`;
  if (!cmp) return stat(label, raw, rawSub);
  const diff = v / cmp.avg - 1;
  const text = Math.abs(diff) < 0.005 ? "평균과 비슷" : `${pct(Math.abs(diff), { digits: 0 })} ${diff < 0 ? "낮음" : "높음"}`;
  return stat(`${label} · 경쟁 평균 대비`, `${text}<span class="stat__raw">(${raw})</span>`,
    `경쟁 ${cmp.n}종목 평균 ${num(cmp.avg, 2)}배 · 낮을수록 저평가`);
}

function renderKeyMetrics(s, peerData = null) {
  const cmp = (key) => (peerData ? peerAverage(peerData, key) : null);
  $("#key-metrics").replaceChildren(h(`<div class="stat-grid">
      ${stat("시가총액", money(s.market_cap, s.currency), s.currency === "USD" ? `≈ ${krw(s.market_cap_krw, { compact: true })}` : "")}
      ${valuationStat("PER", s.per, cmp("per"), "주가 ÷ 주당순이익")}
      ${valuationStat("PBR", s.pbr, cmp("pbr"), "주가 ÷ 주당순자산")}
    </div>`));
}

// ── [S3-A] 재무 추이 ──
// stock.html은 A의 담당 파일 목록에 없어서, 이 파일이 '재무 추이' 칸을 핵심 정보 바로 아래에 만들어 붙인다
const finSection = h(`<details class="section card detail-section fold" open>
    <summary><h2>재무 추이</h2><span class="subtle">연간 매출·영업이익·순이익·영업이익률</span></summary>
    <div class="fold__body" id="financials"></div></details>`);
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

// center·sub를 주면 가운데 글자를 바꾼다(매력도: "상위 p%" — 0~100 숫자 대신 같은 시장 위치, D-003)
function gauge(score, { name = "매력도", center = null, sub = "/ 100", label = null } = {}) {
  const v = score === null ? 0 : Math.max(0, Math.min(100, score));
  const len = Math.PI * 70;   // 반원 길이 (r=70)
  const big = center === null;
  return `<svg class="gauge" viewBox="0 0 168 100" role="img" aria-label="${score === null ? `${name} 계산 불가` : label || `${name} ${num(score, 1)}점`}">
      <path d="M14 90 A70 70 0 0 1 154 90" fill="none" stroke="${color("--card-active")}" stroke-width="14" stroke-linecap="round"/>
      <path d="M14 90 A70 70 0 0 1 154 90" fill="none" stroke="${color("--lavender")}" stroke-width="14" stroke-linecap="round"
        stroke-dasharray="${(len * v) / 100} ${len}"/>
      <text x="84" y="80" text-anchor="middle" font-size="${big ? 30 : 22}" font-weight="800">${score === null ? "–" : big ? Math.round(score) : center}</text>
      <text x="84" y="97" text-anchor="middle" font-size="11" fill="${color("--text-3")}">${sub}</text>
    </svg>`;
}
// 같은 시장 상위 p% (1위도 최소 1%) — 점수(백분위) = 100 × (n − 순위) / n이라 상위 p% = 100 − 점수
const topPercent = (rank) => Math.max(1, Math.ceil((100 * rank.position) / rank.total));

// 매력도 5요소 — 화면 이름은 일상어로(내부 키는 그대로). 레이더 축·요소 카드·계산 근거 표가 같은 이름을 쓴다
const FACTORS = [
  { key: "value", label: "저평가", desc: "일회성을 뺀 이익·가진 자산에 비해 주가가 싼 편인가 (실적이 나빠지는 중이면 감점)" },
  { key: "quality", label: "수익성", desc: "가진 자산과 매출로 돈을 잘 버는가 (최근 연간 기준)" },
  { key: "growth", label: "성장성", desc: "최근 2년 매출과 이익이 늘었나 (성장 정도일 뿐 기대수익이 아님)" },
  { key: "safety", label: "안정성", desc: "주가가 덜 출렁이는가, 자산에 비해 빚이 적은가" },
  { key: "momentum", label: "주가 흐름", desc: "최근 1년 주가가 오르는 추세인가" },
];
const FACTOR_LABEL = Object.fromEntries(FACTORS.map((f) => [f.key, f.label]));
const SIGNED_METRICS = ["revenue_cagr2", "profit_growth2", "momentum"];
const rawFmt = (m) => (m.raw_value === null ? DASH
  : pct(m.raw_value, { digits: 1, sign: SIGNED_METRICS.includes(m.metric) }));
const zFmt = (v) => {
  if (v === null || v === undefined) return DASH;
  const r = Math.round(v * 100) / 100;
  return r === 0 ? "0.00" : `${r > 0 ? "+" : ""}${num(r, 2)}`;
};
// 레이더·요소 카드의 0~100 = 그 팩터의 같은 시장 안 백분위(API factors[k].percentile, 50 = 시장 중앙)
const THEME_FACTORS = ["value", "quality", "growth"];   // 소속 테마 위치에 보여 주는 요소(D-003)
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
    label: "이 종목", data: FACTORS.map((f) => pos[f.key]), borderColor: color("--lavender"), backgroundColor: color("--lavender-fill"),
    borderWidth: 2, pointRadius: 3, pointBackgroundColor: color("--lavender"), spanGaps: true,
  }];
  if (peer) {
    datasets.push({
      label: `${peer.group_name} 평균`, data: FACTORS.map((f) => peer.percentiles?.[f.key] ?? null), borderColor: color("--ice"),
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

// ── [S7-A] 시장·섹터 점수 (매력 점수 아래 위험 표시 — 매력도와 별개, 투자 권유 아님) ──
const INDEX_NAME = { KOSPI: "KOSPI", SPX: "S&P 500" };
const dotDate = (iso) => (iso ? iso.replaceAll("-", ".") : DASH);   // 2026.10.16
const r5 = (v) => (v === null ? DASH : pct(v, { digits: 1, sign: true }));
const round0 = (v) => (v === null ? DASH : Math.round(v));

function conditionRow(mc) {
  const band = scoreBand(mc.score);
  const use = mc.sector_flow !== null;
  const sector = !mc.sector_name ? "<p>섹터 분류가 없어 시장 심리만 반영했습니다</p>"
    : `<p>현재 주식의 섹터 분류는 <strong>${esc(mc.sector_name)}</strong> 입니다</p>${
      use ? "" : "<p>섹터 표본이 적어 시장 심리만 반영했습니다</p>"}`;
  const sectorDate = mc.sector_as_of && mc.sector_as_of !== mc.as_of ? ` (섹터 ${mc.sector_as_of.slice(5).replace("-", ".")})` : "";
  const tip = `<div class="senti__tip score-row__tip" role="tooltip" id="mc-tip"><strong>시장·섹터 점수 ${round0(mc.score)}</strong>
      <span class="score-row__wide">시장 심리 ${round0(mc.sentiment)} · ${
        use ? `섹터 흐름 ${round0(mc.sector_flow)} (${esc(mc.sector_name)} ${mc.sector_sample}종목)` : "섹터 미반영"}</span>
      <span class="score-row__wide score-row__tip-head">5거래일 수익률</span>
      <span>이 종목</span><span class="num">${r5(mc.stock_r5)}</span>
      ${use ? `<span>섹터 중앙값</span><span class="num">${r5(mc.sector_r5)}</span>` : ""}
      <span>${esc(INDEX_NAME[mc.index_code] ?? mc.index_code)}</span><span class="num">${r5(mc.index_r5)}</span>
      <span class="score-row__wide score-row__tip-note">${use ? "시장 심리 70% + 섹터 흐름 30%" : "시장 심리 100%(섹터 미반영)"}, 투자 권유 아님</span>
    </div>`;
  return `<div class="score-row">
      <div class="score-row__gauge senti__gauge" tabindex="0" aria-describedby="mc-tip">
        <h3 class="score-row__title">시장·섹터 점수</h3>${gauge(mc.score, { name: "시장·섹터 점수" })}
        <p class="score-band">${band ? `<i style="background:var(--gauge-${band.index})"></i>` : ""}${esc(mc.label)}</p>
        ${tip}</div>
      <div class="score-row__text score-row__sector">${sector}
        <p class="score-row__date">지수 및 섹터 정보 추합 : ${dotDate(mc.as_of)} 기준${sectorDate}</p></div>
    </div>`;
}

// 원자재 연동 업종 — 연결 원자재 가격의 1년 위치(매력도와 별개의 위험 표시)
function commodityRow(c) {
  const where = c.position_52w === null ? "" : c.position_52w >= 0.67 ? "상단" : c.position_52w <= 0.33 ? "하단" : "중간";
  const quote = c.code && c.close !== null
    ? `<p><strong>${esc(c.name)}</strong> ${num(c.close, 2)} ${esc(c.unit || "")}${
        c.change_1y === null ? "" : ` · 1년 ${pct(c.change_1y, { digits: 1, sign: true })}`}${
        where ? ` · 1년 범위 중 <strong>${where}</strong> (${Math.round(c.position_52w * 100)}%)` : ""}</p>
       <p class="score-row__date">선물 가격 ${dotDate(c.as_of)} 기준</p>`
    : "";
  return `<div class="score-row commodity-row">
      <span class="badge badge--commodity">원자재 연동</span>
      <div class="score-row__text score-row__sector">${quote}<p class="subtle">${esc(c.note)}</p></div>
    </div>`;
}

function renderScore(a) {
  const s = a.attractiveness;
  if (s.unscored_reason) {
    $("#score").replaceChildren(emptyState({ title: "이 업종은 매력도 점수를 내지 않습니다", body: s.unscored_reason }));
    return;
  }
  if (!s.as_of) {
    $("#score").replaceChildren(emptyState({
      title: "매력도가 아직 계산되지 않았습니다",
      body: "사이드바의 새로고침으로 점수를 계산할 수 있습니다." }));
    return;
  }
  const dq = s.data_quality || {};
  const market = s.rank?.country === "US" ? "미국" : "국내";
  const factors = Object.entries(s.factors);
  const pos = Object.fromEntries(FACTORS.map((f) => [f.key, s.factors[f.key]?.available ? (s.factors[f.key].percentile ?? null) : null]));
  const band = scoreBand(s.score);
  const peerWord = `${market}${s.rank?.family === "financial" ? " 금융" : ""} 비교군`;   // 금융은 금융끼리의 순위
  const rankText = !s.rank ? "순위 없음"
    : `${peerWord} ${s.rank.total}개 중 <strong>${s.rank.position}위</strong> <span class="subtle">(상위 ${topPercent(s.rank)}%)</span>`;
  const tp = s.theme_position;
  const themeText = !tp ? "" : `<p class="score-theme subtle">소속 테마 <strong>${esc(tp.group_name)}</strong>는 같은 시장 테마 ${tp.themes}개 중 ${
    THEME_FACTORS.filter((k) => tp.factors[k]).map((k) => `${FACTOR_LABEL[k]} ${tp.factors[k].position}위(상위 ${tp.factors[k].top_percent}%)`).join(" · ")
  } — 테마 안 순위가 높아도 테마 자체가 약할 수 있습니다.</p>`;
  const mc = stock?.market_condition;   // 시장·섹터 점수는 상세 응답에서 — 프리셋을 바꿔 다시 그려도 그대로
  const el = h(`<div class="score-panel">
      <div class="score-panel__gauge score-panel__left">
        <div class="score-row">
          <div class="score-row__gauge"><h3 class="score-row__title">매력도</h3>${gauge(s.score, s.rank
            ? { center: `상위 ${topPercent(s.rank)}%`, sub: "같은 시장 안 위치", label: `매력도 같은 시장 상위 ${topPercent(s.rank)}%` } : {})}
            ${band ? `<p class="score-band"><i style="background:var(--gauge-${band.index})"></i>${band.label}</p>` : ""}</div>
          <div class="score-row__text">
            <p class="score-panel__rank">${rankText}</p>
            <p class="subtle">${esc(s.preset.name)} 성향 · ${date(s.as_of)} 기준</p></div>
        </div>
        ${mc ? conditionRow(mc) : ""}
        ${stock?.commodity ? commodityRow(stock.commodity) : ""}
      </div>
      <div class="score-panel__radar">
        <div class="chart-box chart-box--radar"><canvas role="img" aria-label="매력도 5요소 레이더 (같은 시장 안 백분위 0~100, 50 = 시장 중앙)"></canvas></div>
        <div class="legend"><span><i style="background:${color("--lavender")}"></i>이 종목</span>
          ${s.peer_average ? `<span><i style="background:${color("--ice")}"></i>${esc(s.peer_average.group_name)} 평균 (${s.peer_average.size}종목)</span>` : ""}
          <span><i style="background:${color("--text-3")}"></i>시장 중앙 50</span></div>
        ${themeText}
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
        ${s.fin_basis?.length ? `<p class="subtle">재무 기준 ${s.fin_basis.map((x) => `FY${x.fiscal_year} ${x.stocks}개`).join(" · ")}</p>` : ""}
        <div class="score-panel__factors">
          <h3>팩터 기여도 <span class="subtle">(가중치 × 팩터 점수, 빠진 팩터는 0, 합 = 종합 ${zFmt(s.composite)})</span></h3>
          ${factors.map(([k, f]) => contribRow(k, f, maxAbs)).join("")}
          <p class="subtle">팩터 점수는 같은 시장 안에서 다시 표준화한 Z 단위입니다. 0이 시장 평균, 음수 기여는 왼쪽으로 표시합니다.
            매력도와 레이더·요소 카드의 0~100은 같은 시장 안 백분위입니다(80 이상 = 상위 20%).</p>
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

// ── [S4-A] 한눈에 보는 투자 지표 ──
// 숫자를 '수익성 · 주가 흐름 · 위험' 세 질문으로 묶어 결론 한 줄을 크게, 원래 수치는 작게 둔다.
// 기본은 펼친 상태, 접었다 다시 펼치면 필요할 때만 그린다. stock.html을 못 고쳐서 이 파일이 칸을 만들어 핵심 정보 바로 아래(재무 추이 위)에 붙인다
const foldMetrics = h(`<details class="section card detail-section fold" id="fold-metrics" open>
    <summary><h2>한눈에 보는 투자 지표</h2><span class="subtle">수익성 · 주가 흐름 · 위험</span></summary>
    <div class="fold__body" id="detail-metrics"></div></details>`);
$("#key-metrics").closest("section").after(foldMetrics);

// ---------------------------------------------------------------- 접이식 섹션: 펼쳐져 있을 때 불러온다
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

const has = (v) => typeof v === "number";
const glanceCard = (q, answer, body) => `<div class="glance__card"><span class="glance__q">${q}</span>
    <strong class="glance__a">${answer}</strong>${body}</div>`;
const fact = (label, value, note = "") => `<li>${label} <b class="num">${value}</b>${note ? ` <span>(${note})</span>` : ""}</li>`;

// 수익성: ROE·영업이익률을 경쟁 종목 평균과 비교 (PER·PBR(핵심 정보)과 같은 그룹)
function profitCard(a, peerData) {
  const m = a.metrics;
  if (!has(m.roe) && !has(m.operating_margin)) return glanceCard("돈을 잘 버나 · 수익성", "재무 데이터 없음", "");
  const avg = (key) => (peerData ? peerAverage(peerData, key, { positive: false }) : null);
  const roeAvg = avg("roe"), opmAvg = avg("operating_margin");
  const sides = [[m.roe, roeAvg], [m.operating_margin, opmAvg]].filter(([v, c]) => has(v) && c).map(([v, c]) => Math.sign(v - c.avg));
  let answer;
  if (has(m.operating_margin) && m.operating_margin < 0) answer = "영업 적자 상태";
  else if (!sides.length) answer = "흑자 · 비교할 경쟁 종목 없음";
  else if (sides.every((x) => x > 0)) answer = "경쟁 평균보다 잘 버는 편";
  else if (sides.every((x) => x < 0)) answer = "경쟁 평균보다 덜 버는 편";
  else answer = "경쟁 평균과 비슷한 편";
  const note = (c) => (c ? `경쟁 평균 ${pct(c.avg, { digits: 1 })}` : "");
  return glanceCard("돈을 잘 버나 · 수익성", answer, `<ul class="glance__facts">
      ${fact("ROE", pct(m.roe, { digits: 1 }), note(roeAvg))}
      ${fact("영업이익률", pct(m.operating_margin, { digits: 1 }), note(opmAvg))}
      <li class="glance__basis">${a.fin_period_end ? `FY${a.fin_period_end.slice(0, 4)} · ${esc(a.accounting_std || "")} · ` : ""}ROE = 순이익 ÷ 자본</li></ul>`);
}

// 주가 흐름: 긴 흐름(1년, 없으면 6개월)과 최근(3개월, 없으면 1개월)의 방향 조합
function trendCard(m) {
  const [longLabel, long] = has(m.return_1y) ? ["1년", m.return_1y] : ["6개월", m.return_6m];
  const [shortLabel, short] = has(m.return_3m) ? ["3개월", m.return_3m] : ["1개월", m.return_1m];
  let answer = "데이터 부족";
  if (has(long) && has(short)) {
    answer = long > 0 ? (short >= 0 ? "꾸준히 오르는 흐름" : `${longLabel} 상승 · 최근 쉬는 중`)
      : (short > 0 ? `${longLabel} 하락 · 최근 반등` : "내리는 흐름");
  }
  const chips = [["1주", m.return_1w], ["1개월", m.return_1m], ["3개월", m.return_3m], ["6개월", m.return_6m], ["1년", m.return_1y]]
    .map(([l, v]) => `<span><em>${l}</em>${changeHtml(v, stock.country)}</span>`).join("");
  const ma = has(m.ma120_gap)
    ? `<li class="glance__basis">120일 평균선보다 ${pct(Math.abs(m.ma120_gap), { digits: 1 })} ${m.ma120_gap >= 0 ? "위" : "아래"}${m.ma120 ? ` (${price(m.ma120, stock.currency)})` : ""}</li>` : "";
  return glanceCard("주가는 어떤 흐름인가 · 추세", answer, `<div class="glance__chips">${chips}</div><ul class="glance__facts">${ma}</ul>`);
}

// 위험: 판정 없이 쉬운 말로 — 연환산 변동성 ÷ √252 = 하루 평균 움직임, 최대낙폭 = 1년 중 고점 대비 최대 하락
function riskCard(m) {
  const daily = has(m.volatility_1y) ? m.volatility_1y / Math.sqrt(252) : null;
  const answer = daily === null ? "데이터 부족" : `하루 평균 ±${pct(daily, { digits: 1 })} 움직임`;
  return glanceCard("얼마나 출렁이나 · 위험", answer, `<ul class="glance__facts">
      ${has(m.max_drawdown_1y) ? `<li>1년 중 고점 대비 최대 <b class="num">${pct(Math.abs(m.max_drawdown_1y), { digits: 0 })}</b> 하락한 적 있음</li>` : ""}
      <li class="glance__basis">연환산 변동성 ${pct(m.volatility_1y, { digits: 1 })} · 최대낙폭 ${pct(m.max_drawdown_1y, { digits: 1 })} (최근 252거래일)</li></ul>`);
}

// 거래량: 20일 평균 대비 배수를 말로
function volumeLine(m) {
  const r = m.volume_ratio_20d;
  if (!has(r)) return "";
  const word = r >= 1.5 ? "평소보다 거래가 많음 · 관심 늘어남" : r <= 0.7 ? "평소보다 한산함" : "평소 수준";
  return `<p class="glance__foot">거래량 <strong>${word}</strong> <span>(20일 평균 대비 ${num(r, 2)}배 · 최신 ${num(m.volume)}주)</span></p>`;
}

function paintGlance(a, peerData) {
  const m = a.metrics;
  $("#detail-metrics").replaceChildren(h(`<div class="glance-wrap">
      <div class="glance">${profitCard(a, peerData)}${trendCard(m)}${riskCard(m)}</div>
      ${volumeLine(m)}
      <p class="subtle">결론 문장은 숫자를 쉬운 말로 옮긴 것이며 투자 권유가 아닙니다.</p></div>`));
}

// 경쟁 평균이 오기 전에도 먼저 그리고, 오면 수익성 비교를 채워 다시 그린다
function renderDetailMetrics(a) {
  paintGlance(a, null);
  fetchPeers().then((d) => { if (analysisData === a) paintGlance(a, d); }).catch(() => { /* 비교 없이 표시 */ });
}

fold("metrics", () => {
  if (analysisData) renderDetailMetrics(analysisData);
  else $("#detail-metrics").replaceChildren(emptyState({ title: "지표를 아직 불러오지 못했습니다" }));
});

// ── [S4-A] 경쟁 종목 비교 ──
// stock.html을 못 고쳐서 이 파일이 접이식 칸을 만들어 재무 추이 아래(공시 위)에 붙인다
const foldPeers = h(`<details class="section card detail-section fold" id="fold-peers" open>
    <summary><h2>경쟁 종목 비교</h2><span class="subtle">같은 그룹의 가격 추이·지표 순위</span></summary>
    <div class="fold__body" id="peers"></div></details>`);
finSection.after(foldPeers);

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
const TARGET_COLOR = color("--lavender");
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
    const d = await getPeersChart(MARKET, TICKER, peerRange, groupId);
    let k = 0;
    const lineColor = d.series.map((s) => (s.is_target ? TARGET_COLOR : PEER_COLORS[k++ % PEER_COLORS.length]));
    const el = h(`<div><div class="legend">${d.series.map((s, i) => `<span><i style="background:${lineColor[i]}"></i>${esc(s.name)}${s.is_target ? " (현재)" : ""}</span>`).join("")}</div>
      <div class="chart-box chart-box--sm"><canvas role="img" aria-label="기준일 100 환산 가격 추이"></canvas></div><p class="subtle">${esc(d.note)}</p></div>`);
    box.replaceChildren(el);
    draw(el.querySelector("canvas"), {
      type: "line",
      // 휴장일 null은 선을 끊는다 (spanGaps: false — 원본은 이어 그림)
      data: { labels: d.dates, datasets: d.series.map((s, i) => ({
        label: s.name, data: s.values, borderColor: lineColor[i],
        borderWidth: s.is_target ? 3 : 1.5, pointRadius: 0, tension: 0.2, spanGaps: false })) },
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
    fetch: fetchPeers,
    isEmpty: (d) => !d.groups.length,
    empty: emptyState({ title: "속한 경쟁 그룹이 없습니다" }),
    render: (d) => {
      peers = d;
      groupId = d.groups.find((g) => g.has_peers)?.group_id ?? d.groups[0].group_id;
      return renderPeers();
    },
  });
}

fold("peers", loadPeers);

// ── [S5-A] 월별 요약 (GET /statistics/monthly) ──
// stock.html을 못 고쳐서 이 파일이 접이식 칸을 만들어 재무 추이 아래(경쟁 비교 위)에 붙인다
const foldMonthly = h(`<details class="section card detail-section fold" id="fold-monthly" open>
    <summary><h2>월별 요약</h2><span class="subtle">최근 12개월 거래일·평균 종가·수익률</span></summary>
    <div class="fold__body" id="monthly"></div></details>`);
finSection.after(foldMonthly);

function loadMonthly() {
  return load($("#monthly"), {
    skeleton: skeleton("row", 3),
    fetch: () => getMonthly(MARKET, TICKER, 12),
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

fold("monthly", loadMonthly);

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
  peersReq = null;   // 새로고침 뒤에는 새 값으로
  const shown = stock;
  fetchPeers().then((d) => { if (stock === shown) renderKeyMetrics(stock, d); }).catch(() => { /* 비교 없이 원래 수치만 */ });
  loadCandles();
  loadFinancials();   // [S3-A]
  loadDisclosures();  // [S3-A]
  mountPresetControl();   // [S4-A] 성향 메뉴(한 번만)
  loadAnalysis();         // [S4-A] 매력도
  reloadFold("monthly");  // [S5-A] 월별 요약(펼쳐져 있으면 다시, 접혀 있으면 다음에 펼칠 때)
  reloadFold("peers");    // [S4-A] 경쟁 비교(펼쳐져 있으면 다시, 접혀 있으면 다음에 펼칠 때)
}
init();

// ── [S3-A] 사이드바 새로고침이 끝나면 상세 화면을 새 값으로 다시 불러온다 ──
document.addEventListener(REFRESHED_EVENT, init);
