// 담기 폼: 포트폴리오 선택 + 모드(수량/금액/비중) + 값 → 미리보기 → POST
// - openAddToPortfolio(stock): 주식 리스트·종목 상세의 "담기" 모달
// - renderAddForm(container, opts): 모의 포트폴리오 화면의 인라인 담기 패널
// 미리보기는 화면 계산(참고용)이고, 실제 수량·원가·시드 검증은 서버가 Decimal로 다시 계산한다.
import { Market, Portfolios } from "../api.js";
import { esc, krw, num, price } from "../format.js";
import { h, openModal, segmented, toast } from "./ui.js";

const MODES = [
  { value: "quantity", label: "수량", unit: "주", placeholder: "예: 10" },
  { value: "amount", label: "금액", unit: "원", placeholder: "예: 3000000" },
  { value: "weight", label: "비중", unit: "%", placeholder: "예: 20" },
];

/**
 * stock: {market, ticker, name, close, currency}
 * opts: {portfolios, fx, portfolioId(고정 시), onDone(item), onCancel}
 */
export function renderAddForm(container, stock, { portfolios, fx, portfolioId, onDone, onCancel }) {
  const rate = stock.currency === "USD" ? fx.usd_krw : 1;
  const unit = stock.close * rate;           // 1주 원가(원)
  let mode = "amount";
  const fixed = portfolioId != null;

  const form = h(`<form novalidate class="add-form">
      <p class="subtle">기준가 ${price(stock.close, stock.currency)}${stock.currency === "USD" ? ` × 환율 ${num(rate, 2)}${fx.fx_stale ? " (지연된 환율)" : ""}` : ""}
        = 1주 ${krw(unit)}</p>
      <div class="field" ${fixed ? "hidden" : ""}><label for="pf-select">포트폴리오</label>
        <select id="pf-select" class="select">${portfolios.map((p) => `<option value="${p.portfolio_id}">${esc(p.name)} · 잔여 ${krw(p.remaining_krw, { compact: true })}</option>`).join("")}</select></div>
      <div class="field"><span class="field__label" id="mode-label">입력 방식</span><div data-mode></div></div>
      <div class="field"><label for="pf-value" data-value-label>금액 (원)</label>
        <input id="pf-value" class="input num" inputmode="decimal" autocomplete="off" required></div>
      <dl class="preview" aria-live="polite" data-preview></dl>
      <p class="notice notice--warn" data-error hidden></p>
      <div class="modal__foot">${onCancel ? '<button class="btn" type="button" data-cancel>취소</button>' : ""}
        <button class="btn btn--primary" type="submit">담기</button></div>
    </form>`);
  container.replaceChildren(form);
  const select = form.querySelector("#pf-select");
  if (fixed) select.value = String(portfolioId);
  const input = form.querySelector("#pf-value");
  const preview = form.querySelector("[data-preview]");
  const errorBox = form.querySelector("[data-error]");
  const current = () => portfolios.find((p) => p.portfolio_id === Number(select.value));
  const value = () => Number(input.value.replace(/[,\s]/g, ""));
  const showError = (msg, html = false) => { errorBox.hidden = false; errorBox[html ? "innerHTML" : "textContent"] = msg; };

  const update = () => {
    const m = MODES.find((x) => x.value === mode);
    form.querySelector("[data-value-label]").textContent = `${m.label} (${m.unit})`;
    input.placeholder = m.placeholder;
    const pf = current();
    const v = value();
    let qty = 0;
    if (v > 0) {
      if (mode === "quantity") qty = Math.floor(v);
      else if (mode === "amount") qty = Math.floor(v / unit);
      else qty = Math.floor((pf.seed_krw * v) / 100 / unit);
    }
    const cost = qty * unit;
    const remaining = pf.remaining_krw - cost;
    preview.innerHTML = `
      <dt>예상 수량</dt><dd class="num">${num(qty)}주</dd>
      <dt>예상 원가</dt><dd class="num">${krw(cost)}</dd>
      <dt>담은 뒤 잔여 현금</dt><dd class="num" style="color:${remaining < 0 ? "var(--danger)" : "inherit"}">${krw(remaining)}</dd>`;
    errorBox.hidden = true;
    if (v > 0 && qty === 0) showError(`1주를 담으려면 최소 ${krw(Math.ceil(unit))}이 필요합니다.`);
    else if (remaining < 0) showError(`시드를 ${krw(-remaining)} 초과합니다. 최대 ${num(Math.max(0, Math.floor(pf.remaining_krw / unit)))}주까지 담을 수 있습니다.`);
  };

  form.querySelector("[data-mode]").append(segmented(MODES, mode, (v) => { mode = v; input.value = ""; update(); input.focus(); },
    { label: "입력 방식", variant: "segmented--card" }));
  input.addEventListener("input", update);
  select.addEventListener("change", update);
  form.querySelector("[data-cancel]")?.addEventListener("click", onCancel);
  update();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!(value() > 0)) { showError("0보다 큰 값을 입력해 주세요."); input.focus(); return; }
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const item = await Portfolios.addItem(Number(select.value), { market: stock.market, ticker: stock.ticker, mode, value: value() });
      toast(`${current().name}에 ${stock.name} ${num(item.quantity)}주를 담았습니다 (${krw(item.cost_krw)})`);
      onDone?.(item);
    } catch (err) {
      const d = err.detail || {};
      if (err.code === "SEED_EXCEEDED") showError(`시드를 넘습니다. 잔여 ${krw(d.remaining_krw)} · 최대 ${num(d.max_quantity)}주까지 담을 수 있습니다.`);
      else if (err.code === "QUANTITY_ZERO") showError(`수량이 0주입니다. 최소 ${krw(d.min_amount_krw)}이 필요합니다.`);
      else if (err.code === "DUPLICATE_ITEM") showError(`이미 담은 종목입니다. <a href="/portfolio?id=${Number(select.value)}" style="text-decoration:underline">포트폴리오에서 수정</a>해 주세요.`, true);
      else showError(err.message);
    } finally {
      submit.disabled = false;
    }
  });
  return form;
}

/** 주식 리스트·종목 상세의 "담기" 모달 */
export async function openAddToPortfolio(stock) {
  const body = h('<div class="add-form"><div class="skeleton skeleton--row"></div></div>');
  const modal = openModal({ title: `${stock.name} 담기`, body });
  let portfolios, fx;
  try {
    [portfolios, fx] = await Promise.all([Portfolios.list(), stock.currency === "USD" ? Market.fx() : null]);
  } catch (e) {
    body.replaceChildren(h(`<p class="notice notice--warn">${esc(e.message)}</p>`));
    return;
  }
  if (!portfolios.length) {
    body.replaceChildren(h(`<div class="state"><p class="state__title">포트폴리오가 없습니다</p>
      <p>먼저 시드를 정해 포트폴리오를 만들어 주세요.</p><a class="btn btn--primary" href="/portfolio">포트폴리오 만들기</a></div>`));
    return;
  }
  renderAddForm(body, stock, { portfolios, fx, onDone: () => modal.close(), onCancel: () => modal.close() });
  body.querySelector("#pf-value")?.focus();
}
