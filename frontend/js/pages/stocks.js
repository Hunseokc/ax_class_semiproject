// 주식 리스트: 시장 탭·정렬(거래량/시총)·검색·경쟁 그룹·업종 섹터 필터, 25개씩 페이지
import { PRESET_EVENT, getPeerGroups, getPreset, getStocks } from "../api.js";   // [S4-A] PRESET_EVENT·getPreset
import { changeHtml, dateTime, esc, initials, krw, price, stockUrl, volume } from "../format.js";
import { mountSidebar } from "../components/sidebar.js";
import { emptyState, h, load, marketBadge, segmented, skeleton } from "../components/ui.js";
import { icons } from "../components/icons.js";   // [S2-A]
import { openAddToPortfolio } from "../components/add-to-portfolio.js";   // [S2-A]
import { starButton } from "../components/watch.js";   // [S2-A]
import { scoreBadge } from "../components/charts.js";   // [S4-A]
import { loadPresets, mountPresetMenu } from "../components/preset-menu.js";   // [S4-A]

mountSidebar("stocks");
const $ = (sel) => document.querySelector(sel);

// 상태는 URL 쿼리와 동기화 (홈의 '더 보기' 링크가 탭·정렬을 지정해 들어온다)
const qs = new URLSearchParams(location.search);
// 업종 섹터 — backend/config/universe.yaml sectors와 같아야 한다(서버는 그 밖의 값을 422로 거절)
const SECTORS = ["반도체·전자", "IT·인터넷", "헬스케어", "자동차·운송장비", "산업재", "에너지·유틸리티", "소재", "필수소비재", "경기소비재", "금융"];
const PAGE_SIZE = 25;
const state = {
  country: ["KR", "US"].includes(qs.get("country")) ? qs.get("country") : "",
  sort: qs.get("sort") === "volume" ? "volume" : "market_cap",
  group: qs.get("group") || "",
  sector: SECTORS.includes(qs.get("sector")) ? qs.get("sector") : "",
  q: qs.get("q") || "",
  page: Math.max(1, Number.parseInt(qs.get("page"), 10) || 1),
};
// '전체' 탭은 시장마다 거래량 단위가 달라 시총 정렬만 허용
if (!state.country && state.sort === "volume") state.sort = "market_cap";

function syncUrl() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) if (v && !(k === "page" && v === 1)) p.set(k, v);
  const preset = new URLSearchParams(location.search).get("preset");   // [S4-A] 투자 성향은 api.js가 관리하는 값이라 지우지 않는다
  if (preset) p.set("preset", preset);
  history.replaceState(null, "", `${location.pathname}${p.size ? `?${p}` : ""}`);
}

// ---------------------------------------------------------------- 컨트롤
const marketTabs = segmented([{ value: "", label: "전체" }, { value: "KR", label: "국내" }, { value: "US", label: "미국" }],
  state.country, (v) => {
    state.country = v;
    if (!v && state.sort === "volume") { state.sort = "market_cap"; }
    renderSortTabs();
    refresh({ resetPage: true });
  }, { label: "시장" });
$("#market-tabs").append(marketTabs);

function renderSortTabs() {
  const all = !state.country;
  const tabs = segmented([
    { value: "volume", label: "거래량", disabled: all, title: "전체 탭에서는 시장마다 거래량 단위가 달라 정렬할 수 없습니다. 국내/미국 탭을 선택하세요." },
    { value: "market_cap", label: "시가총액" },
  ], state.sort, (v) => { state.sort = v; refresh({ resetPage: true }); }, { label: "정렬 기준", variant: "segmented--card" });
  $("#sort-tabs").replaceChildren(tabs);
  $("#sort-hint").hidden = !all;
}
renderSortTabs();

const search = $("#search");
search.value = state.q;
let timer;
search.addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(() => { state.q = search.value.trim(); refresh({ resetPage: true }); }, 250);   // 입력이 멈춘 뒤 한 번만 조회
});

const groupSel = $("#group");
getPeerGroups().then(({ groups }) => {
  groupSel.append(...groups.map((g) => h(`<option value="${esc(g.name)}">${esc(g.name)} (${g.size})</option>`)));
  groupSel.value = state.group;
}).catch(() => { groupSel.disabled = true; });
groupSel.addEventListener("change", () => { state.group = groupSel.value; refresh({ resetPage: true }); });

const sectorSel = $("#sector");
sectorSel.append(...SECTORS.map((s) => h(`<option value="${esc(s)}">${esc(s)}</option>`)));
sectorSel.value = state.sector;
sectorSel.addEventListener("change", () => { state.sector = sectorSel.value; refresh({ resetPage: true }); });

// ── [S4-A] 투자 성향: 대시보드·종목 상세와 같은 값 (헤더 오른쪽 펼침 메뉴) ──
// stocks.html은 A의 담당 파일 목록에 없어서, 이 파일이 메뉴 자리를 시장 탭 옆에 만들어 붙인다
const presetBox = h('<div id="preset-menu"></div>');
$("#market-tabs").after(presetBox);
let presetNames = {};
let lastList = null;
const renderMeta = () => {
  if (!lastList) return;
  const { d, sortLabel } = lastList;
  const preset = presetNames[getPreset()] ? ` · 매력도 ${presetNames[getPreset()]} 기준` : "";
  $("#list-meta").textContent = `${d.total}개 종목 · ${sortLabel} 순${preset} · 시총 환산 환율 기준 ${dateTime(d.fx_rate_at)}`;
};
loadPresets().then(({ presets }) => {
  presetNames = Object.fromEntries(presets.map((p) => [p.code, p.name]));
  renderMeta();
});
mountPresetMenu(presetBox);
document.addEventListener(PRESET_EVENT, () => refresh());   // 성향이 바뀌면 같은 조건(같은 페이지)으로 다시 조회

// ---------------------------------------------------------------- 리스트
function stockRow(s) {
  const li = h(`<li class="stock-row">
      <span class="rank">${s.rank}</span>
      <a class="stock-row__name" href="${stockUrl(s.market, s.ticker)}?preset=${encodeURIComponent(getPreset())}">
        <span class="avatar" aria-hidden="true">${esc(initials(s.name))}</span>
        <span class="row__main"><span class="row__title">${esc(s.name)}</span>
          <span class="row__sub">${esc(s.ticker)} ${marketBadge(s.market, s.country)}${
            s.sector ? ` <span class="badge badge--sector">${esc(s.sector)}</span>` : ""}</span></span>
      </a>
      <span class="stock-row__price num"><strong>${price(s.close, s.currency)}</strong>${changeHtml(s.change_rate, s.country)}</span>
      <span class="stock-row__col num" data-label="거래량">${volume(s.volume)}</span>
      <span class="stock-row__col num" data-label="시총(원화)">${krw(s.market_cap_krw, { compact: true })}</span>
      <span class="stock-row__score">${scoreBadge(s.score)}</span>
      <span class="stock-row__actions"></span>
    </li>`);
  const add = h(`<button class="btn btn--sm btn--accent" type="button" aria-label="${esc(s.name)} 포트폴리오에 담기">${icons.plus}<span>담기</span></button>`);
  add.addEventListener("click", () => openAddToPortfolio(s));
  li.querySelector(".stock-row__actions").append(starButton(s, s.is_watched), add);
  return li;
}

// 페이지 이동: 이전 · n / 전체 · 다음 (순위는 전체 기준이라 페이지가 바뀌어도 이어진다)
function renderPager(total) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pager = $("#pager");
  pager.hidden = pages <= 1;
  if (pages <= 1) return pager.replaceChildren();
  const btn = (label, page, disabled) => {
    const b = h(`<button class="btn btn--sm" type="button"${disabled ? " disabled" : ""}>${label}</button>`);
    b.addEventListener("click", () => { state.page = page; refresh(); $("#h-list").scrollIntoView({ block: "start" }); });
    return b;
  };
  pager.replaceChildren(btn("이전", state.page - 1, state.page <= 1),
    h(`<span class="pager__pos num" aria-current="page">${state.page} / ${pages}</span>`),
    btn("다음", state.page + 1, state.page >= pages));
}

function refresh({ resetPage = false } = {}) {
  if (resetPage) state.page = 1;
  syncUrl();
  const sortLabel = state.sort === "volume" ? "거래량" : "시가총액(원화 환산)";
  return load($("#list"), {
    skeleton: skeleton("row", 8),
    fetch: () => getStocks({ country: state.country, sort: state.sort, group: state.group, sector: state.sector, q: state.q,
                             limit: PAGE_SIZE, offset: (state.page - 1) * PAGE_SIZE }),
    isEmpty: (d) => !d.items.length,
    render: (d) => {
      lastList = { d, sortLabel };   // [S4-A]
      renderMeta();
      renderPager(d.total);
      const ul = h('<ul class="list stock-list" aria-label="종목 순위"></ul>');
      ul.append(h(`<li class="stock-row stock-row--head" aria-hidden="true"><span>#</span><span>종목</span><span>현재가·등락</span>
        <span class="stock-row__col">거래량</span><span class="stock-row__col">시총(원화)</span><span>매력도</span><span></span></li>`));   // [S4-A] 매력도 열
      ul.append(...d.items.map(stockRow));
      return ul;
    },
    empty: emptyState({ title: "조건에 맞는 종목이 없습니다", body: "검색어나 경쟁 그룹·섹터 필터를 바꿔 보세요." }),
  });
}

refresh();
