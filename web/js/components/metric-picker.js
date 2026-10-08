// 대시보드 '주요 지수 · 환율'에 표시할 지표 선택 — 카드 줄 아래 펼침 박스. 선택은 브라우저에 저장한다.
import { esc } from "../format.js";
import { icons } from "./icons.js";
import { h } from "./ui.js";

const KEY = "marketMetrics";
export const FX_CODE = "USDKRW";
export const DEFAULT_METRICS = ["KOSPI", "KOSDAQ", "SPX", "IXIC", "DJI", FX_CODE];

/** 저장된 선택(없거나 지금 없는 지표는 빼고). 남는 게 없으면 기본값 → 그것도 없으면 첫 지표 */
export function storedMetrics(available) {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY)); } catch { saved = null; }
  const pick = (codes) => (Array.isArray(codes) ? codes.filter((c) => available.includes(c)) : []);
  const valid = pick(saved);
  if (valid.length) return valid;
  const defaults = pick(DEFAULT_METRICS);
  return defaults.length ? defaults : available.slice(0, 1);
}

function saveMetrics(codes) {
  try { localStorage.setItem(KEY, JSON.stringify(codes)); } catch { /* 저장 불가(사생활 보호 모드 등)면 이번 화면에서만 유지 */ }
}

/**
 * groups: [{ label, items: [{ code, name }] }] — 이 순서가 카드 순서
 * onChange(codes): 선택이 바뀔 때마다(즉시 반영), onClose(): 완료
 */
export function metricPicker({ id, groups, selected, onChange, onClose }) {
  const order = groups.flatMap((g) => g.items.map((i) => i.code));
  let current = order.filter((c) => selected.includes(c));
  const root = h(`<div class="card picker" id="${esc(id)}" role="region" aria-label="표시할 지표 선택" hidden>
      <div class="picker__head"><h3>표시할 지표를 선택하세요</h3><span class="subtle" aria-live="polite"></span></div>
      ${groups.map((g) => `<div class="picker__group" role="group" aria-label="${esc(g.label)}">
          <span class="picker__group-label">${esc(g.label)}</span>
          <div class="picker__chips">${g.items.map((i) => `<button type="button" class="chip" data-code="${esc(i.code)}">
              <span class="chip__check">${icons.check}</span>${esc(i.name)}</button>`).join("")}</div>
        </div>`).join("")}
      <div class="picker__foot">
        <button type="button" class="btn btn--sm" data-act="reset">기본값으로</button>
        <button type="button" class="btn btn--sm btn--primary" data-act="done">완료</button>
      </div>
    </div>`);
  const chips = [...root.querySelectorAll(".chip")];
  const count = root.querySelector(".picker__head .subtle");

  function paint() {
    chips.forEach((b) => {
      const on = current.includes(b.dataset.code);
      const last = on && current.length === 1;
      b.setAttribute("aria-pressed", String(on));
      b.disabled = last;                                   // 최소 1개는 표시
      b.title = last ? "최소 1개는 표시해야 합니다" : "";
    });
    count.textContent = `${current.length}/${order.length}개 표시`;
  }

  function set(codes) {
    const next = order.filter((c) => codes.includes(c));
    if (!next.length) return;
    current = next;
    saveMetrics(current);
    paint();
    onChange(current);
  }

  chips.forEach((b) => b.addEventListener("click", () => {
    const c = b.dataset.code;
    set(current.includes(c) ? current.filter((x) => x !== c) : [...current, c]);
  }));
  root.querySelector('[data-act="reset"]').addEventListener("click", () => set(DEFAULT_METRICS));
  root.querySelector('[data-act="done"]').addEventListener("click", onClose);
  root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } });

  paint();
  return root;
}
