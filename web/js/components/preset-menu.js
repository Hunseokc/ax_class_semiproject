// 투자 성향 선택 펼침 메뉴 — 현재 값만 보여 주는 버튼 + 누르면 펼쳐지는 listbox (대시보드·주식 리스트·종목 상세 공통)
import { PRESET_EVENT, Scoring, getPreset, setPreset } from "../api.js";
import { esc } from "../format.js";
import { icons } from "./icons.js";
import { h } from "./ui.js";

// 프리셋 code → 색 토큰 (색은 이 맵 한 곳에서만 관리)
export const PRESET_COLOR = {
  aggressive: "--preset-aggressive",
  growth: "--preset-growth",
  balanced: "--preset-balanced",
  value: "--preset-value",
};

// GET /scoring/presets 실패 시 쓰는 기본값
const FALLBACK = {
  note: "공개된 일반적 투자 스타일을 단순화한 가중치이며 특정 인물의 판단이 아닙니다.",
  presets: [
    { code: "aggressive", name: "위험", description: "모멘텀·성장 중심", sort_order: 1 },
    { code: "growth", name: "성장", description: "성장성 중심", sort_order: 2 },
    { code: "balanced", name: "균형", description: "5개 팩터 균등", sort_order: 3 },
    { code: "value", name: "가치", description: "저평가·안정성 중심", sort_order: 4 },
  ],
};

let cache = null;
/** { note, presets(sort_order 순) } — 한 화면에서 한 번만 요청 */
export function loadPresets() {
  cache ??= Scoring.presets()
    .then((d) => ({ note: d.note, presets: [...d.presets].sort((a, b) => a.sort_order - b.sort_order) }))
    .catch(() => FALLBACK);
  return cache;
}

export const presetDot = (code) =>
  `<span class="preset-dot" style="background:var(${PRESET_COLOR[code] || "--text-3"})" aria-hidden="true"></span>`;

let seq = 0;

export async function mountPresetMenu(container) {
  const { presets } = await loadPresets();
  const listId = `preset-list-${++seq}`;
  const root = h(`<div class="preset-menu">
      <button type="button" class="preset-menu__trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="${listId}">
        <span class="preset-menu__label">투자 성향</span><span class="preset-menu__current"></span>${icons.chevronDown}
      </button>
      <ul class="preset-menu__list" id="${listId}" role="listbox" aria-label="투자 성향" hidden></ul>
    </div>`);
  const trigger = root.querySelector("button");
  const list = root.querySelector("ul");
  const options = presets.map((p) => {
    const li = h(`<li role="option" tabindex="-1" class="preset-menu__option" data-code="${esc(p.code)}">
        ${presetDot(p.code)}<span class="preset-menu__text"><strong>${esc(p.name)}</strong><small>${esc(p.description || "")}</small></span>
        <span class="preset-menu__check">${icons.check}</span></li>`);
    li.addEventListener("click", () => select(p.code));
    return li;
  });
  list.append(...options);

  const byCode = (code) => presets.find((p) => p.code === code) || presets.find((p) => p.code === "balanced") || presets[0];
  const isOpen = () => !list.hidden;

  function paint() {
    const cur = byCode(getPreset());
    trigger.querySelector(".preset-menu__current").innerHTML = `${presetDot(cur.code)}<strong>${esc(cur.name)}</strong>`;
    trigger.setAttribute("aria-label", `투자 성향: ${cur.name}`);
    options.forEach((o) => o.setAttribute("aria-selected", String(o.dataset.code === cur.code)));
  }

  function place() {
    // 768px 미만: 화면 폭에 맞춘 고정 패널(트리거 바로 아래), 그 외: 트리거 아래 오른쪽 정렬
    if (window.innerWidth < 768) {
      list.style.top = `${trigger.getBoundingClientRect().bottom + 8}px`;
      list.classList.add("preset-menu__list--fixed");
    } else {
      list.style.top = "";
      list.classList.remove("preset-menu__list--fixed");
    }
  }

  function open() {
    if (isOpen()) return;
    list.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    place();
    (options.find((o) => o.getAttribute("aria-selected") === "true") || options[0]).focus();
  }

  function close({ focusTrigger = false } = {}) {
    if (!isOpen()) return;
    list.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (focusTrigger) trigger.focus();
  }

  function select(code) {
    close({ focusTrigger: true });
    if (code !== getPreset()) setPreset(code);
  }

  trigger.addEventListener("click", () => (isOpen() ? close() : open()));
  trigger.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); open(); }
  });
  list.addEventListener("keydown", (e) => {
    const i = options.indexOf(document.activeElement);
    const move = (j) => { e.preventDefault(); options[Math.max(0, Math.min(options.length - 1, j))].focus(); };
    if (e.key === "ArrowDown") move(i + 1);
    else if (e.key === "ArrowUp") move(i - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(options.length - 1);
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (i >= 0) select(options[i].dataset.code); }
    else if (e.key === "Escape") { e.preventDefault(); close({ focusTrigger: true }); }
    else if (e.key === "Tab") close();
  });
  root.addEventListener("focusout", (e) => { if (!root.contains(e.relatedTarget)) close(); });
  document.addEventListener("pointerdown", (e) => { if (!root.contains(e.target)) close(); });
  window.addEventListener("resize", () => { if (isOpen()) place(); });
  window.addEventListener("scroll", () => { if (isOpen()) place(); }, { passive: true });
  document.addEventListener(PRESET_EVENT, paint);

  paint();
  container.replaceChildren(root);
  return root;
}
