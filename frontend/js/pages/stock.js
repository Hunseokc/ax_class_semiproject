// 종목 상세: 헤더(이름·가격·등락) · 가격 차트(종가 선 + 거래량 막대) · 핵심 정보(시총·PER·PBR)
import { getCandles, getDisclosures, getFinancials, getStock } from "../api.js";
import { DASH, changeHtml, date, esc, krw, num, pct, price, usd } from "../format.js";
import { color, dashedAxis, draw, plainAxis } from "../components/charts.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";   // [S3-A] REFRESHED_EVENT
import { emptyState, errorState, h, load, marketBadge, segmented, skeleton } from "../components/ui.js";
import { icons } from "../components/icons.js";   // [S2-A]
import { openAddToPortfolio } from "../components/add-to-portfolio.js";   // [S2-A]
import { starButton } from "../components/watch.js";   // [S2-A]

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
}
init();

// ── [S3-A] 사이드바 새로고침이 끝나면 상세 화면을 새 값으로 다시 불러온다 ──
document.addEventListener(REFRESHED_EVENT, init);
