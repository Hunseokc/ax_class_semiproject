// 공통 UI: 상태(스켈레톤·빈·오류), 토스트, 모달, 세그먼트 탭, 점수 뱃지, 시장 뱃지
import { esc } from "../format.js";
import { icons } from "./icons.js";

export const h = (html) => {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
};

// ---------------------------------------------------------------- 상태
export function skeleton(kind = "row", n = 4) {
  const wrap = h(`<div class="${kind === "card" ? "wl-grid" : "list"}" aria-busy="true" aria-label="불러오는 중"></div>`);
  for (let i = 0; i < n; i++) wrap.append(h(`<div class="skeleton skeleton--${kind}"></div>`));
  return wrap;
}

export function emptyState({ title, body = "", action = "" }) {
  return h(`<div class="state" role="status">
      <div class="state__icon">${icons.inbox}</div>
      <p class="state__title">${esc(title)}</p>
      ${body ? `<p>${body}</p>` : ""}${action}
    </div>`);
}

export function errorState(err, onRetry) {
  const el = h(`<div class="state state--error" role="alert">
      <div class="state__icon">${icons.alert}</div>
      <p class="state__title">데이터를 불러오지 못했습니다</p>
      <p>${esc(err?.message || "알 수 없는 오류")}</p>
      ${onRetry ? '<button class="btn btn--sm" type="button">다시 시도</button>' : ""}
    </div>`);
  el.querySelector("button")?.addEventListener("click", onRetry);
  return el;
}

/** 영역을 로딩 → 데이터/빈/오류 상태로 채운다 */
export async function load(container, { skeleton: sk, fetch, render, empty, isEmpty = (d) => !d || (Array.isArray(d) && !d.length) }) {
  container.replaceChildren(sk || skeleton());
  try {
    const data = await fetch();
    if (isEmpty(data) && empty) container.replaceChildren(empty);
    else container.replaceChildren(render(data));
    return data;
  } catch (err) {
    console.error(err);
    container.replaceChildren(errorState(err, () => load(container, { skeleton: sk, fetch, render, empty, isEmpty })));
    return null;
  }
}

// ---------------------------------------------------------------- 토스트
export function toast(message, type = "info") {
  let wrap = document.getElementById("toasts");
  if (!wrap) {
    wrap = h('<div id="toasts" class="toast-wrap" aria-live="polite"></div>');
    document.body.append(wrap);
  }
  const el = h(`<div class="toast ${type === "error" ? "toast--error" : ""}" role="${type === "error" ? "alert" : "status"}">${esc(message)}</div>`);
  wrap.append(el);
  setTimeout(() => el.remove(), 3800);
}

// ---------------------------------------------------------------- 모달
export function openModal({ title, body, onClose }) {
  const prev = document.activeElement;
  const backdrop = h(`<div class="modal-backdrop">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal__head"><h2 id="modal-title">${esc(title)}</h2>
          <button class="btn btn--icon" type="button" aria-label="닫기" data-close>${icons.close}</button></div>
      </div></div>`);
  const modal = backdrop.querySelector(".modal");
  modal.append(body);
  const close = () => {
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
    prev?.focus?.();
    onClose?.();
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    if (e.key === "Tab") {                       // 모달 안에서만 포커스 순환
      const f = [...modal.querySelectorAll("button, input, select, a[href]")].filter((x) => !x.disabled);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
    }
  };
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop || e.target.closest("[data-close]")) close(); });
  document.addEventListener("keydown", onKey);
  document.body.append(backdrop);
  (modal.querySelector("input, select, .btn--primary") || modal.querySelector("button"))?.focus();
  return { close, el: modal };
}

// ---------------------------------------------------------------- 세그먼트 탭
/**
 * options: [{value, label, disabled?, title?}]  → 선택 시 onChange(value)
 * 키보드: 좌우 화살표로 이동 (role=tablist)
 */
export function segmented(options, value, onChange, { label = "", variant = "" } = {}) {
  const el = h(`<div class="segmented ${variant}" role="tablist" aria-label="${esc(label)}"></div>`);
  const render = (current) => {
    el.replaceChildren(...options.map((o) => {
      const b = h(`<button type="button" role="tab">${esc(o.label)}</button>`);
      b.setAttribute("aria-selected", String(o.value === current));
      b.tabIndex = o.value === current ? 0 : -1;
      if (o.disabled) { b.disabled = true; b.title = o.title || ""; }
      b.addEventListener("click", () => { if (o.value !== current) { render(o.value); onChange(o.value); } });
      return b;
    }));
  };
  el.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const btns = [...el.querySelectorAll("button:not(:disabled)")];
    const i = btns.indexOf(document.activeElement);
    const next = btns[(i + (e.key === "ArrowRight" ? 1 : -1) + btns.length) % btns.length];
    next?.focus();
    next?.click();
  });
  render(value);
  el.setValue = render;
  return el;
}

// ---------------------------------------------------------------- 뱃지
export function scoreBadge(score) {
  return score === null || score === undefined
    ? '<span class="score score--none" title="매력도 데이터 부족">–</span>'
    : `<span class="score" title="매력도 ${score}점 (같은 시장 안 상대적 위치, 투자 권유 아님)">${Math.round(score)}</span>`;
}

// ---------------------------------------------------------------- 매력도 미니 게이지 (관심종목 카드)
const BANDS = ["매우 낮음", "낮음", "보통", "높음", "매우 높음"];

/** 0~100 점수 → 5구간 {index 1~5, label}. 점수가 없으면 null */
export function scoreBand(score) {
  if (score === null || score === undefined) return null;
  const i = Math.min(4, Math.floor(Math.max(0, score) / 20));
  return { index: i + 1, label: BANDS[i] };
}

const GX = 46, GY = 48, GR = 36;
const gp = (deg) => `${(GX + GR * Math.cos((deg * Math.PI) / 180)).toFixed(2)} ${(GY - GR * Math.sin((deg * Math.PI) / 180)).toFixed(2)}`;
const garc = (from, to) => `M ${gp(from)} A ${GR} ${GR} 0 0 1 ${gp(to)}`;

/** 반원 게이지: 5구간(테라코타~청록, 현재 구간만 진하게) + 바늘 + 점수·구간 라벨. 점수 없으면 점선 + '데이터 부족' */
export function scoreGauge(score) {
  const band = scoreBand(score);
  if (!band) {
    return `<div class="gauge-mini gauge-mini--na">
        <svg viewBox="0 0 92 54" aria-hidden="true"><path class="gauge-mini__ticks" d="${garc(180, 0)}"/></svg>
        <div class="gauge-mini__value"><strong>–</strong><span class="gauge-mini__band"><i class="gauge-mini__ring"></i>데이터 부족</span></div>
      </div>`;
  }
  const segs = BANDS.map((_, i) => `<path d="${garc(180 - i * 36 - 1.5, 180 - (i + 1) * 36 + 1.5)}"
      stroke="var(--gauge-${i + 1})" opacity="${i + 1 === band.index ? 1 : 0.3}"/>`).join("");
  const angle = Math.max(0, Math.min(100, score)) * 1.8 - 90;
  return `<div class="gauge-mini">
      <svg viewBox="0 0 92 54" aria-hidden="true"><g class="gauge-mini__arc">${segs}</g>
        <g class="gauge-mini__needle" style="transform:rotate(${angle.toFixed(1)}deg)">
          <line x1="${GX}" y1="${GY}" x2="${GX}" y2="${GY - 29}"/><circle cx="${GX}" cy="${GY}" r="3.5"/></g></svg>
      <div class="gauge-mini__value"><strong class="num">${Math.round(score)}</strong>
        <span class="gauge-mini__band"><i style="background:var(--gauge-${band.index})"></i>${band.label}</span></div>
    </div>`;
}

export function marketBadge(market, country) {
  return `<span class="badge ${country === "US" ? "badge--us" : "badge--kr"}">${esc(market)}</span>`;
}
