// 주식 리스트: 시장 탭·정렬(거래량/시총)·검색·경쟁 그룹 필터, ★ 관심 토글, 담기
import { Scoring, Stocks, scorePreset } from "../api.js";
import { changeHtml, dateTime, esc, initials, krw, price, stockUrl, volume } from "../format.js";
import { openAddToPortfolio } from "../components/add-to-portfolio.js";
import { icons } from "../components/icons.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";
import { emptyState, h, load, marketBadge, scoreBadge, segmented, skeleton } from "../components/ui.js";
import { starButton } from "../components/watch.js";

mountSidebar("stocks");
const $ = (sel) => document.querySelector(sel);

// 상태는 URL 쿼리와 동기화 (홈의 '더 보기' 링크가 탭·정렬을 지정해 들어온다)
const qs = new URLSearchParams(location.search);
const state = {
  country: ["KR", "US"].includes(qs.get("country")) ? qs.get("country") : "",
  sort: qs.get("sort") === "volume" ? "volume" : "market_cap",
  group: qs.get("group") || "",
  q: qs.get("q") || "",
};
// '전체' 탭은 시장마다 거래량 단위가 달라 시총 정렬만 허용
if (!state.country && state.sort === "volume") state.sort = "market_cap";

function syncUrl() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) if (v) p.set(k, v);
  history.replaceState(null, "", `${location.pathname}${p.size ? `?${p}` : ""}`);
}

// ---------------------------------------------------------------- 컨트롤
const marketTabs = segmented([{ value: "", label: "전체" }, { value: "KR", label: "국내" }, { value: "US", label: "미국" }],
  state.country, (v) => {
    state.country = v;
    if (!v && state.sort === "volume") { state.sort = "market_cap"; }
    renderSortTabs();
    refresh();
  }, { label: "시장" });
$("#market-tabs").append(marketTabs);

function renderSortTabs() {
  const all = !state.country;
  const tabs = segmented([
    { value: "volume", label: "거래량", disabled: all, title: "전체 탭에서는 시장마다 거래량 단위가 달라 정렬할 수 없습니다. 국내/미국 탭을 선택하세요." },
    { value: "market_cap", label: "시가총액" },
  ], state.sort, (v) => { state.sort = v; refresh(); }, { label: "정렬 기준", variant: "segmented--card" });
  $("#sort-tabs").replaceChildren(tabs);
  $("#sort-hint").hidden = !all;
}
renderSortTabs();

const search = $("#search");
search.value = state.q;
let timer;
search.addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(() => { state.q = search.value.trim(); refresh(); }, 250);
});

const groupSel = $("#group");
Stocks.groups().then(({ groups }) => {
  groupSel.append(...groups.map((g) => h(`<option value="${esc(g.name)}">${esc(g.name)} (${g.size})</option>`)));
  groupSel.value = state.group;
}).catch(() => { groupSel.disabled = true; });
groupSel.addEventListener("change", () => { state.group = groupSel.value; refresh(); });

// 매력도 프리셋: 브라우저에 기억해 홈 관심종목 카드·종목 상세와 같은 기준으로 보여 준다
const presetSel = $("#preset");
let presetNames = {};
let lastList = null;
const renderMeta = () => {
  if (!lastList) return;
  const { d, sortLabel } = lastList;
  const preset = presetNames[d.preset] ? ` · 매력도 ${presetNames[d.preset]} 기준` : "";
  $("#list-meta").textContent = `${d.total}개 종목 · ${sortLabel} 순${preset} · 시총 환산 환율 기준 ${dateTime(d.fx_rate_at)}`;
};
Scoring.presets().then(({ presets }) => {
  presetNames = Object.fromEntries(presets.map((p) => [p.code, p.name]));
  presetSel.append(...presets.map((p) => h(`<option value="${esc(p.code)}">매력도: ${esc(p.name)}</option>`)));
  presetSel.value = presetNames[scorePreset.get()] ? scorePreset.get() : "balanced";
  renderMeta();
}).catch(() => { presetSel.disabled = true; });
presetSel.addEventListener("change", () => { scorePreset.set(presetSel.value); refresh(); });

// ---------------------------------------------------------------- 리스트
function stockRow(s) {
  const li = h(`<li class="stock-row">
      <span class="rank">${s.rank}</span>
      <a class="stock-row__name" href="${stockUrl(s.market, s.ticker)}">
        <span class="avatar" aria-hidden="true">${esc(initials(s.name))}</span>
        <span class="row__main"><span class="row__title">${esc(s.name)}</span>
          <span class="row__sub">${esc(s.ticker)} ${marketBadge(s.market, s.country)}</span></span>
      </a>
      <span class="stock-row__price num"><strong>${price(s.close, s.currency)}</strong>${changeHtml(s.change_rate, s.country)}</span>
      <span class="stock-row__col num" data-label="거래량">${volume(s.volume)}</span>
      <span class="stock-row__col num" data-label="시총(원화)">${krw(s.market_cap_krw, { compact: true })}</span>
      <span class="stock-row__score">${scoreBadge(s.score)}</span>
      <span class="stock-row__actions"></span>
    </li>`);
  const actions = li.querySelector(".stock-row__actions");
  const add = h(`<button class="btn btn--sm btn--accent" type="button" aria-label="${esc(s.name)} 포트폴리오에 담기">${icons.plus}<span>담기</span></button>`);
  add.addEventListener("click", () => openAddToPortfolio(s));
  actions.append(starButton(s, s.is_watched), add);
  return li;
}

function refresh() {
  syncUrl();
  const sortLabel = state.sort === "volume" ? "거래량" : "시가총액(원화 환산)";
  return load($("#list"), {
    skeleton: skeleton("row", 8),
    fetch: () => Stocks.list({ country: state.country, sort: state.sort, group: state.group, q: state.q }),
    isEmpty: (d) => !d.items.length,
    render: (d) => {
      lastList = { d, sortLabel };
      renderMeta();
      const ul = h('<ul class="list stock-list" aria-label="종목 순위"></ul>');
      ul.append(h(`<li class="stock-row stock-row--head" aria-hidden="true"><span>#</span><span>종목</span><span>현재가·등락</span>
        <span class="stock-row__col">거래량</span><span class="stock-row__col">시총(원화)</span><span>매력도</span><span></span></li>`));
      ul.append(...d.items.map(stockRow));
      return ul;
    },
    empty: emptyState({ title: "조건에 맞는 종목이 없습니다", body: "검색어나 경쟁 그룹 필터를 바꿔 보세요." }),
  });
}

document.addEventListener(REFRESHED_EVENT, refresh);
refresh();
