// 상단 검색: 상장 보통주 전체(노출 종목·비교군·상장 종목 목록) 자동완성 → 종목 상세로 이동
// ARIA combobox(목록 상자) · ↑↓ 이동 · Enter 열기 · Esc 닫기 · '/' 키로 검색창 포커스
// 이어 입력하면 이전 요청은 취소하고(AbortController) 마지막 입력의 결과만 보여 준다
import { Stocks } from "../api.js";
import { esc, stockUrl } from "../format.js";
import { icons } from "./icons.js";
import { h, marketBadge } from "./ui.js";

const DEBOUNCE_MS = 150;
const COVERAGE_NOTE = { listed: "열면 데이터를 불러옵니다" };

export function mountSearch() {
  const inner = document.querySelector(".main__inner");
  if (!inner || document.getElementById("gsearch")) return;
  const el = h(`<div class="topbar" role="search">
      <div class="gsearch" id="gsearch">
        <label class="search"><span class="sr-only">종목 검색</span>${icons.search}
          <input class="input" type="search" placeholder="종목 이름·티커 검색" title="국내·미국 상장 보통주 전체에서 찾습니다" autocomplete="off"
            role="combobox" aria-expanded="false" aria-autocomplete="list" aria-controls="gsearch-list"></label>
        <kbd class="gsearch__key" aria-hidden="true">/</kbd>
        <div class="gsearch__panel" hidden>
          <ul class="gsearch__list" id="gsearch-list" role="listbox" aria-label="검색 결과"></ul>
          <p class="gsearch__status subtle" role="status" aria-live="polite"></p>
        </div>
      </div></div>`);
  inner.prepend(el);

  const input = el.querySelector("input");
  const panel = el.querySelector(".gsearch__panel");
  const list = el.querySelector(".gsearch__list");
  const status = el.querySelector(".gsearch__status");
  let items = [], active = -1, timer = 0, ctrl = null, lastQ = "";

  const open = (on) => { panel.hidden = !on; input.setAttribute("aria-expanded", String(on)); };
  const setActive = (i) => {
    active = i;
    list.querySelectorAll("[role=option]").forEach((o, k) => o.setAttribute("aria-selected", String(k === i)));
    const cur = list.children[i];
    if (cur) { input.setAttribute("aria-activedescendant", cur.id); cur.scrollIntoView({ block: "nearest" }); }
    else input.removeAttribute("aria-activedescendant");
  };
  const go = (it) => { if (it) location.href = stockUrl(it.market, it.ticker); };

  function render(q) {
    list.replaceChildren(...items.map((it, i) => {
      const li = h(`<li role="option" id="gsearch-opt-${i}" aria-selected="false" class="gsearch__item">
          <span class="gsearch__name"><strong>${esc(it.name)}</strong>
            ${it.name_en && it.name_en !== it.name ? `<span class="subtle">${esc(it.name_en)}</span>` : ""}</span>
          <span class="gsearch__meta"><span class="subtle num">${esc(it.ticker)}</span> ${marketBadge(it.market, it.country)}
            ${COVERAGE_NOTE[it.coverage] ? `<span class="gsearch__note">${COVERAGE_NOTE[it.coverage]}</span>` : ""}</span></li>`);
      li.addEventListener("mousedown", (e) => e.preventDefault());   // 클릭 전에 입력창 blur로 닫히지 않게
      li.addEventListener("click", () => go(it));
      li.addEventListener("mousemove", () => { if (active !== i) setActive(i); });
      return li;
    }));
    status.textContent = items.length ? `${items.length}개 결과` : `'${q}'에 해당하는 종목이 없습니다`;
    setActive(items.length ? 0 : -1);
    open(true);
  }

  async function run(q) {
    ctrl?.abort();
    if (!q) { items = []; list.replaceChildren(); open(false); return; }
    ctrl = new AbortController();
    status.textContent = "검색 중…";
    try {
      const d = await Stocks.search(q, ctrl.signal);
      if (q !== lastQ) return;
      items = d.items;
      render(q);
    } catch (e) {
      if (e.name === "AbortError") return;
      items = [];
      list.replaceChildren();
      status.textContent = `검색하지 못했습니다: ${e.message}`;
      open(true);
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    lastQ = input.value.trim();
    timer = setTimeout(() => run(lastQ), DEBOUNCE_MS);
  });
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;                       // 한글 조합 중 Enter·화살표는 IME가 처리
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!items.length) return;
      e.preventDefault();
      if (panel.hidden) open(true);
      setActive((active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(items[active] || items[0]);
    } else if (e.key === "Escape") {
      if (!panel.hidden) open(false);
      else { input.value = ""; lastQ = ""; items = []; }
    }
  });
  input.addEventListener("focus", () => { if (items.length) open(true); });
  input.addEventListener("blur", () => open(false));
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    if (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
    e.preventDefault();
    input.focus();
  });
}
