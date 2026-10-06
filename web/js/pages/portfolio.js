// 모의 포트폴리오: 선택·생성·삭제, 시드 수정, 종목 담기(검색+모드+미리보기), 담은 목록(수정·삭제), 요약·비중 차트
// 체결 기록이 아니라 "시드 안에서 담아보는 계산기"다.
import { Market, Portfolios, Stocks } from "../api.js";
import { DASH, changeHtml, dateTime, esc, initials, krw, num, pct, price, signedKrw, stockUrl } from "../format.js";
import { renderAddForm } from "../components/add-to-portfolio.js";
import { color, dashedAxis, draw, plainAxis } from "../components/charts.js";
import { icons } from "../components/icons.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";
import { emptyState, errorState, h, openModal, segmented, skeleton, toast } from "../components/ui.js";

mountSidebar("portfolio");
const $ = (sel) => document.querySelector(sel);
const DONUT = ["#e6f4fa", "#e6ddf2", "#5ea8ff", "#f5c26b", "#4fd1c5", "#f0a6ca", "#9ccc65", "#b39ddb"];

let portfolios = [];
let currentId = Number(new URLSearchParams(location.search).get("id")) || null;
let universe = null;   // 담기 검색용 종목 목록

const pnlClass = (v) => (v > 0 ? "chg chg--kr-up" : v < 0 ? "chg chg--kr-down" : "chg chg--flat");   // 원화 손익은 국내 관례 색
const pnlHtml = (v, rate) => (v === null ? DASH : `<span class="${pnlClass(v)}">${signedKrw(v)}${rate !== null && rate !== undefined ? ` (${pct(rate, { sign: true })})` : ""}</span>`);

// ---------------------------------------------------------------- 포트폴리오 목록·선택
async function loadPortfolios() {
  $("#picker").replaceChildren(h('<div class="skeleton" style="height:44px;width:320px;border-radius:999px"></div>'));
  try {
    portfolios = await Portfolios.list();
  } catch (e) {
    $("#picker").replaceChildren();
    $("#content").replaceChildren(errorState(e, loadPortfolios));
    return;
  }
  if (!portfolios.length) {
    $("#picker").replaceChildren();
    const empty = emptyState({ title: "포트폴리오가 없습니다", body: "시드(투자 가능 금액)를 정해 첫 포트폴리오를 만들어 보세요.",
      action: '<button class="btn btn--primary" type="button" data-create>포트폴리오 만들기</button>' });
    empty.querySelector("[data-create]").addEventListener("click", () => editPortfolio(null));
    $("#content").replaceChildren(empty);
    return;
  }
  if (!portfolios.some((p) => p.portfolio_id === currentId)) currentId = portfolios[0].portfolio_id;
  $("#picker").replaceChildren(segmented(portfolios.map((p) => ({ value: p.portfolio_id, label: p.name })), currentId,
    (v) => { currentId = v; loadPortfolio(); }, { label: "포트폴리오 선택" }));
  loadPortfolio();
}

function editPortfolio(pf) {
  const body = h(`<form class="add-form" novalidate>
      <div class="field"><label for="pf-name">이름</label><input id="pf-name" class="input" maxlength="100" required value="${esc(pf?.name || "")}"></div>
      <div class="field"><label for="pf-seed">시드 (원)</label><input id="pf-seed" class="input num" inputmode="numeric" required value="${pf ? pf.seed_krw : ""}" placeholder="예: 10000000">
        <span class="subtle" data-seed-hint>${pf ? `현재 담은 원가 ${krw(pf.used_krw)} — 시드는 이보다 작게 줄일 수 없습니다` : ""}</span></div>
      <p class="notice notice--warn" data-error hidden></p>
      <div class="modal__foot"><button class="btn" type="button" data-close>취소</button><button class="btn btn--primary" type="submit">${pf ? "저장" : "만들기"}</button></div>
    </form>`);
  const modal = openModal({ title: pf ? "포트폴리오 수정" : "새 포트폴리오", body });
  const err = body.querySelector("[data-error]");
  const seedInput = body.querySelector("#pf-seed");
  seedInput.addEventListener("input", () => {
    const v = Number(seedInput.value.replace(/[,\s]/g, ""));
    if (!pf) body.querySelector("[data-seed-hint]").textContent = v > 0 ? `= ${krw(v, { compact: true })}` : "";
  });
  body.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = body.querySelector("#pf-name").value.trim();
    const seed = Number(seedInput.value.replace(/[,\s]/g, ""));
    if (!name || !(seed > 0) || !Number.isInteger(seed)) { err.hidden = false; err.textContent = "이름과 0보다 큰 정수 시드(원)를 입력해 주세요."; return; }
    try {
      const saved = pf ? await Portfolios.update(pf.portfolio_id, name, seed) : await Portfolios.create(name, seed);
      currentId = saved.portfolio_id;
      history.replaceState(null, "", `/portfolio?id=${currentId}`);
      modal.close();
      toast(pf ? "포트폴리오를 수정했습니다" : "포트폴리오를 만들었습니다");
      loadPortfolios();
    } catch (ex) {
      err.hidden = false;
      err.textContent = ex.code === "SEED_BELOW_USED"
        ? `시드를 담은 원가 합계(${krw(ex.detail.used_krw)})보다 작게 줄일 수 없습니다.` : ex.message;
    }
  });
}

function confirmDelete(title, message, onConfirm) {
  const body = h(`<div class="add-form"><p>${message}</p>
      <div class="modal__foot"><button class="btn" type="button" data-close>취소</button><button class="btn btn--danger" type="button" data-ok>삭제</button></div></div>`);
  const modal = openModal({ title, body });
  body.querySelector("[data-ok]").addEventListener("click", async () => {
    try { await onConfirm(); modal.close(); } catch (e) { toast(e.message, "error"); }
  });
}

// ---------------------------------------------------------------- 선택한 포트폴리오
async function loadPortfolio() {
  history.replaceState(null, "", `/portfolio?id=${currentId}`);
  const pf = portfolios.find((p) => p.portfolio_id === currentId);
  $("#content").replaceChildren(skeleton("card", 4));
  let s;
  try {
    s = await Portfolios.summary(currentId);
  } catch (e) {
    $("#content").replaceChildren(errorState(e, loadPortfolio));
    return;
  }
  const wrap = h('<div class="pf"></div>');
  wrap.append(renderToolbar(pf, s), renderSummary(s));
  const grid = h('<div class="pf-grid"><section class="section card" aria-labelledby="h-add"><h2 id="h-add">종목 담기</h2><div id="add-panel"></div></section><section class="section card" aria-labelledby="h-weights"><h2 id="h-weights">비중</h2><div id="weights"></div></section></div>');
  wrap.append(grid, renderItems(s), h(`<p class="disclaimer">${esc(s.disclaimer)} 담은 시점의 종가·환율로 원가를 고정하며, 평가금액은 최신 종가 × 현재 환율입니다. 체결 기록이 아닙니다.</p>`));
  $("#content").replaceChildren(wrap);
  renderAddPanel(s);
  renderWeights(s);
}

function renderToolbar(pf, s) {
  const el = h(`<div class="pf-toolbar"><div><h2>${esc(s.name)}</h2><p class="subtle">시드 ${krw(s.seed_krw)} · 기준일 ${s.as_of ? s.as_of : DASH}</p></div>
      <div class="pf-toolbar__actions"><button class="btn btn--sm" type="button" data-edit>이름·시드 수정</button>
        <button class="btn btn--sm btn--danger" type="button" data-del aria-label="${esc(s.name)} 포트폴리오 삭제">삭제</button></div></div>`);
  el.querySelector("[data-edit]").addEventListener("click", () => editPortfolio({ ...pf, used_krw: s.used_krw }));
  el.querySelector("[data-del]").addEventListener("click", () => confirmDelete("포트폴리오 삭제",
    `<strong>${esc(s.name)}</strong>과(와) 담은 종목 ${s.items.length}개를 모두 삭제합니다.`, async () => {
      await Portfolios.remove(currentId);
      toast("포트폴리오를 삭제했습니다");
      currentId = null;
      loadPortfolios();
    }));
  return el;
}

function renderSummary(s) {
  const usage = s.usage_rate ?? 0;
  const tile = (label, value, sub = "", cls = "") => `<div class="stat ${cls}"><span class="stat__label">${label}</span><span class="stat__value num">${value}</span>${sub ? `<span class="stat__sub">${sub}</span>` : ""}</div>`;
  return h(`<section class="section" aria-label="요약"><div class="pf-summary">
      <div class="card card--ice pf-summary__hero">
        <span class="subtle">총 평가금액</span>
        <span class="pf-summary__big num">${krw(s.total_value_krw + s.remaining_krw)}</span>
        <span class="subtle">담은 종목 ${krw(s.total_value_krw)} + 현금 ${krw(s.remaining_krw)}</span>
        <span class="pf-summary__pnl num">${s.items.length ? pnlHtml(s.total_pnl_krw, s.total_pnl_rate) : "담은 종목 없음"}</span>
      </div>
      <div class="stat-grid">
        ${tile("시드", krw(s.seed_krw))}
        ${tile("사용 금액(원가)", krw(s.used_krw), `<div class="bar" role="img" aria-label="사용률 ${pct(usage, { digits: 1 })}" style="margin-top:6px"><div class="bar__fill" style="width:${Math.min(100, usage * 100)}%"></div></div>사용률 ${pct(usage, { digits: 1 })}`)}
        ${tile("잔여 현금", krw(s.remaining_krw))}
        ${tile("가중평균 매력도", s.weighted_score === null ? DASH : num(s.weighted_score, 1), "원가 비중 가중")}
        ${tile("가격 효과", signedKrw(s.price_effect_krw), "종목통화 가격 변화 × 담은 시점 환율")}
        ${tile("환율 효과", signedKrw(s.fx_effect_krw), "현재가 × 환율 변화")}
        ${tile("환율 기준", s.fx_rate ? num(s.fx_rate, 2) : "해당 없음", s.fx_rate_at ? `${dateTime(s.fx_rate_at)}${s.fx_stale ? " · 지연된 환율" : ""}` : "USD 종목 없음")}
      </div></div></section>`);
}

function renderItems(s) {
  const sec = h('<section class="section" aria-labelledby="h-items"><div class="section__head"><h2 id="h-items">담은 종목</h2><span class="subtle">원가 기준 비중</span></div></section>');
  if (!s.items.length) {
    sec.append(emptyState({ title: "아직 담은 종목이 없습니다", body: "위의 '종목 담기'에서 수량·금액·비중으로 담아 보세요." }));
    return sec;
  }
  const ul = h('<ul class="list card card--flush" aria-label="담은 종목"></ul>');
  for (const it of s.items) {
    const li = h(`<li class="pf-item">
        <a class="pf-item__name" href="${stockUrl(it.market, it.ticker)}"><span class="avatar" aria-hidden="true">${esc(initials(it.name))}</span>
          <span class="row__main"><span class="row__title">${esc(it.name)}</span>
            <span class="row__sub">${esc(it.ticker)} · ${num(it.quantity)}주 · 기준 ${price(it.ref_price, it.currency)}${it.currency === "USD" ? ` × ${num(it.ref_fx_rate, 2)}` : ""} (${it.ref_date})</span></span></a>
        <span class="pf-item__col num"><span class="stat__label">원가 · 비중</span><strong>${krw(it.cost_krw)}</strong><span class="subtle">${pct(it.weight, { digits: 1 })}</span></span>
        <span class="pf-item__col num"><span class="stat__label">현재 평가</span><strong>${krw(it.value_krw)}</strong><span class="subtle">${price(it.current_price, it.currency)} ${changeHtml(it.local_return, it.country, { digits: 1 })}</span></span>
        <span class="pf-item__col num"><span class="stat__label">평가손익</span><strong>${pnlHtml(it.pnl_krw, it.pnl_rate)}</strong>
          <span class="subtle">${it.currency === "USD" ? `가격 ${signedKrw(it.price_effect_krw)} · 환율 ${signedKrw(it.fx_effect_krw)}` : "원화 종목"}</span></span>
        <span class="pf-item__actions"></span></li>`);
    const edit = h(`<button class="btn btn--sm" type="button" aria-label="${esc(it.name)} 수정">수정</button>`);
    const del = h(`<button class="btn btn--sm btn--danger" type="button" aria-label="${esc(it.name)} 삭제">삭제</button>`);
    edit.addEventListener("click", () => editItem(it));
    del.addEventListener("click", () => confirmDelete("담은 종목 삭제", `<strong>${esc(it.name)}</strong> ${num(it.quantity)}주를 포트폴리오에서 뺍니다.`, async () => {
      await Portfolios.removeItem(currentId, it.item_id);
      toast(`${it.name}을(를) 뺐습니다`);
      refreshCurrent();
    }));
    li.querySelector(".pf-item__actions").append(edit, del);
    ul.append(li);
  }
  sec.append(ul);
  return sec;
}

function editItem(it) {
  let mode = "quantity";
  const body = h(`<form class="add-form" novalidate>
      <p class="subtle">수정하면 기준가·환율이 현재값으로 다시 저장됩니다. 현재 ${num(it.quantity)}주 · 원가 ${krw(it.cost_krw)}</p>
      <div class="field"><span class="field__label">입력 방식</span><div data-mode></div></div>
      <div class="field"><label for="it-value" data-label>수량 (주)</label><input id="it-value" class="input num" inputmode="decimal" value="${it.quantity}"></div>
      <div class="field"><label for="it-memo">메모</label><input id="it-memo" class="input" maxlength="500" value="${esc(it.memo || "")}"></div>
      <p class="notice notice--warn" data-error hidden></p>
      <div class="modal__foot"><button class="btn" type="button" data-close>취소</button><button class="btn btn--primary" type="submit">저장</button></div>
    </form>`);
  const units = { quantity: "수량 (주)", amount: "금액 (원)", weight: "비중 (%)" };
  body.querySelector("[data-mode]").append(segmented(
    [{ value: "quantity", label: "수량" }, { value: "amount", label: "금액" }, { value: "weight", label: "비중" }], mode,
    (v) => { mode = v; body.querySelector("[data-label]").textContent = units[v]; body.querySelector("#it-value").value = ""; },
    { label: "입력 방식", variant: "segmented--card" }));
  const modal = openModal({ title: `${it.name} 수정`, body });
  const err = body.querySelector("[data-error]");
  body.addEventListener("submit", async (e) => {
    e.preventDefault();
    const value = Number(body.querySelector("#it-value").value.replace(/[,\s]/g, ""));
    if (!(value > 0)) { err.hidden = false; err.textContent = "0보다 큰 값을 입력해 주세요."; return; }
    try {
      const r = await Portfolios.updateItem(currentId, it.item_id, { mode, value, memo: body.querySelector("#it-memo").value });
      toast(`${it.name} ${num(r.quantity)}주로 수정했습니다`);
      modal.close();
      refreshCurrent();
    } catch (ex) {
      err.hidden = false;
      const d = ex.detail || {};
      err.textContent = ex.code === "SEED_EXCEEDED" ? `시드를 넘습니다. 이 종목은 최대 ${num(d.max_quantity)}주까지 담을 수 있습니다.`
        : ex.code === "QUANTITY_ZERO" ? `수량이 0주입니다. 최소 ${krw(d.min_amount_krw)}이 필요합니다.`
        : ex.code === "VALIDATION_ERROR" ? "입력 값을 확인해 주세요(수량은 정수, 비중은 100% 이하)." : ex.message;
    }
  });
}

// ---------------------------------------------------------------- 담기 패널 (종목 검색 → 폼)
async function renderAddPanel(s) {
  const panel = $("#add-panel");
  if (!universe) {
    panel.replaceChildren(skeleton("row", 1));
    try { universe = (await Stocks.list({ limit: 100 })).items; } catch (e) { panel.replaceChildren(errorState(e, () => renderAddPanel(s))); return; }
  }
  const held = new Set(s.items.map((i) => i.stock_id));
  const box = h(`<div class="add-form">
      <label class="search"><span class="sr-only">담을 종목 검색</span>${icons.search}
        <input class="input" list="stock-options" placeholder="종목명·티커 검색 후 선택" autocomplete="off"></label>
      <datalist id="stock-options">${universe.map((u) => `<option value="${esc(u.name)} · ${esc(u.ticker)} · ${esc(u.market)}${held.has(u.stock_id) ? " (담김)" : ""}"></option>`).join("")}</datalist>
      <div data-form><p class="subtle">종목을 고르면 수량·금액·비중으로 담고, 입력하는 동안 예상 수량·원가·잔여 현금을 미리 보여줍니다.</p></div></div>`);
  panel.replaceChildren(box);
  const input = box.querySelector("input");
  let shown = null;   // 지금 폼을 띄운 종목 — 같은 종목으로 change가 다시 와도(포커스 이동 등) 입력값을 지우지 않는다
  input.addEventListener("change", async () => {
    const [, ticker, market] = input.value.split(" · ").map((x) => x.replace(" (담김)", "").trim());
    const st = universe.find((u) => u.ticker === ticker && u.market === market);
    if (st && shown === st.stock_id) return;
    shown = st?.stock_id ?? null;
    const target = box.querySelector("[data-form]");
    if (!st) { target.replaceChildren(h('<p class="notice">목록에서 종목을 선택해 주세요.</p>')); return; }
    if (held.has(st.stock_id)) { target.replaceChildren(h(`<p class="notice">${esc(st.name)}은(는) 이미 담겨 있습니다. 아래 목록에서 수정하세요.</p>`)); return; }
    const fx = st.currency === "USD" ? await Market.fx() : null;
    const pfRow = { portfolio_id: currentId, name: s.name, seed_krw: s.seed_krw, remaining_krw: s.remaining_krw };
    renderAddForm(target, st, { portfolios: [pfRow], fx, portfolioId: currentId, onDone: refreshCurrent });
  });
}

// ---------------------------------------------------------------- 비중 차트
function renderWeights(s) {
  const box = $("#weights");
  if (!s.items.length) { box.replaceChildren(emptyState({ title: "담은 종목이 없어 비중을 계산할 수 없습니다" })); return; }
  const el = h(`<div class="pf-weights">
      <div class="pf-donut"><canvas role="img" aria-label="종목별 원가 비중 도넛 차트"></canvas>
        <div class="pf-donut__center"><span class="subtle">사용률</span><strong class="num">${pct(s.usage_rate, { digits: 0 })}</strong></div></div>
      <div class="legend pf-legend">${s.items.map((it, i) => `<span><i style="background:${DONUT[i % DONUT.length]}"></i>${esc(it.name)} ${pct(it.weight, { digits: 1 })}</span>`).join("")}</div>
      <h3>시장별</h3><div class="chart-box" style="height:${36 + s.market_weights.length * 34}px"><canvas data-market role="img" aria-label="시장별 비중 막대"></canvas></div>
      <h3>경쟁 그룹별</h3><div class="chart-box" style="height:${36 + s.group_weights.length * 34}px"><canvas data-group role="img" aria-label="경쟁 그룹별 비중 막대"></canvas></div>
    </div>`);
  box.replaceChildren(el);
  draw(el.querySelector(".pf-donut canvas"), {
    type: "doughnut",
    data: { labels: s.items.map((i) => i.name), datasets: [{ data: s.items.map((i) => i.cost_krw), backgroundColor: s.items.map((_, i) => DONUT[i % DONUT.length]), borderWidth: 0, borderRadius: 6, spacing: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: "70%",
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.label} ${krw(ctx.raw)} (${pct(s.items[ctx.dataIndex].weight, { digits: 1 })})` } } } },
  });
  const hbar = (canvas, labels, weights) => draw(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data: weights.map((w) => w * 100), backgroundColor: color("--lavender"), borderRadius: 8, barThickness: 18 }] },
    options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
      scales: { x: { ...dashedAxis, max: 100, ticks: { callback: (v) => `${v}%` } }, y: plainAxis },
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.raw.toFixed(1)}%` } } } },
  });
  hbar(el.querySelector("[data-market]"), s.market_weights.map((m) => (m.country === "KR" ? "국내" : "미국")), s.market_weights.map((m) => m.weight));
  hbar(el.querySelector("[data-group]"), s.group_weights.map((g) => g.group), s.group_weights.map((g) => g.weight));
}

// ---------------------------------------------------------------- 시작
async function refreshCurrent() {
  try { portfolios = await Portfolios.list(); } catch { /* 목록 갱신 실패 시 기존 값 유지 */ }
  loadPortfolio();
}
$("#create").addEventListener("click", () => editPortfolio(null));
document.addEventListener(REFRESHED_EVENT, refreshCurrent);
loadPortfolios();
