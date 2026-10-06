// 대시보드 홈: 지수·환율 카드, 내 관심종목, 거래량 상위 5
import { Market, Stocks, Watchlist } from "../api.js";
import { changeHtml, date, dateTime, esc, initials, num, price, shortDate, stockUrl, volume } from "../format.js";
import { color, sparkline } from "../components/charts.js";
import { REFRESHED_EVENT, mountSidebar } from "../components/sidebar.js";
import { emptyState, h, load, marketBadge, scoreBadge, segmented, skeleton } from "../components/ui.js";

mountSidebar("home");

const $ = (sel) => document.querySelector(sel);
const trendColor = (rate, country) => {
  if (!rate) return color("--text-2");
  if (country === "US") return rate > 0 ? color("--us-up") : color("--us-down");
  return rate > 0 ? color("--kr-up") : color("--kr-down");
};

// ---------------------------------------------------------------- 지수·환율
function indexCard(ix) {
  const el = h(`<article class="metric-card" aria-label="${esc(ix.name)}">
      <div class="metric-card__label"><span title="${esc(ix.name)}">${esc(ix.name)}</span><span class="subtle">${esc(ix.country || "")}</span></div>
      <div class="metric-card__value num">${num(ix.close, 2)}</div>
      <div class="metric-card__spark"><canvas aria-hidden="true"></canvas></div>
      <div class="metric-card__foot">${changeHtml(ix.change_rate, ix.country)}<span class="subtle" title="기준일 ${date(ix.as_of)}">${shortDate(ix.as_of)}</span></div>
    </article>`);
  queueMicrotask(() => sparkline(el.querySelector("canvas"), ix.sparkline.map((p) => p.close), trendColor(ix.change_rate, ix.country)));
  return el;
}

function fxCard(fx) {
  const el = h(`<article class="metric-card" aria-label="원달러 환율">
      <div class="metric-card__label"><span>USD/KRW</span>${fx.fx_stale ? '<span class="badge badge--market" title="최신 환율을 가져오지 못해 마지막 값을 표시합니다">지연</span>' : '<span class="subtle">환율</span>'}</div>
      <div class="metric-card__value num">${num(fx.usd_krw, 2)}<span class="subtle">원</span></div>
      <div class="metric-card__spark"><canvas aria-hidden="true"></canvas></div>
      <div class="metric-card__foot">${changeHtml(fx.change_rate, "KR")}<span class="subtle" title="환율 기준 시각 ${dateTime(fx.rate_at)}">${dateTime(fx.rate_at).slice(-5)}</span></div>
    </article>`);
  queueMicrotask(() => sparkline(el.querySelector("canvas"), [...fx.history.map((p) => p.usd_krw), fx.usd_krw], color("--lavender")));
  return el;
}

async function loadMarket() {
  const box = $("#market");
  box.replaceChildren(skeleton("card", 6));
  box.firstElementChild.className = "metric-grid";
  const [ix, fx] = await Promise.allSettled([Market.indices(), Market.fx()]);
  const grid = h('<div class="metric-grid"></div>');
  if (ix.status === "fulfilled") {
    grid.append(...ix.value.indices.map(indexCard));
    $("#as-of").textContent = `일봉 기준 · 기준일 ${date(ix.value.as_of)}`;
  }
  if (fx.status === "fulfilled") grid.append(fxCard(fx.value));
  if (ix.status === "rejected" || fx.status === "rejected") {
    const err = (ix.reason || fx.reason);
    const card = h(`<div class="state state--error" role="alert"><p class="state__title">일부 지표를 불러오지 못했습니다</p>
      <p>${esc(err.message)}</p><button class="btn btn--sm" type="button">다시 시도</button></div>`);
    card.querySelector("button").addEventListener("click", loadMarket);
    grid.append(card);
  }
  box.replaceChildren(grid);
}

// ---------------------------------------------------------------- 관심종목
function watchCard(w, i) {
  return h(`<a class="wl-card card--link ${i % 2 ? "card--lavender" : "card--ice"}" href="${stockUrl(w.market, w.ticker)}"
        aria-label="${esc(w.name)} 상세 보기">
      <div class="wl-card__top"><span class="wl-card__dots" aria-hidden="true"><i></i><i></i></span>${scoreBadge(w.score)}</div>
      <div><div class="wl-card__ticker">${esc(w.ticker)} · ${esc(w.market)}</div>
        <div class="wl-card__price num">${price(w.close, w.currency)}</div></div>
      <div class="wl-card__foot"><span class="wl-card__name">${esc(w.name)}</span>${changeHtml(w.change_rate, w.country)}</div>
    </a>`);
}

function loadWatchlist() {
  return load($("#watchlist"), {
    skeleton: skeleton("card", 4),
    fetch: async () => (await Watchlist.list()).items,
    render: (items) => {
      const grid = h('<div class="wl-grid"></div>');
      grid.append(...items.map(watchCard));
      return grid;
    },
    empty: emptyState({ title: "관심종목이 없습니다", body: "주식 리스트에서 ★로 추가하세요.", action: '<a class="btn btn--primary" href="/stocks">주식 리스트로 가기</a>' }),
  });
}

// ---------------------------------------------------------------- 거래량 상위 5
let topCountry = "KR";
function volumeRow(s) {
  return h(`<li><a class="row" href="${stockUrl(s.market, s.ticker)}">
      <span style="display:flex;align-items:center;gap:12px"><span class="rank">${s.rank}</span><span class="avatar" aria-hidden="true">${esc(initials(s.name))}</span></span>
      <span class="row__main"><span class="row__title">${esc(s.name)}</span>
        <span class="row__sub">${esc(s.ticker)} ${marketBadge(s.market, s.country)} ${price(s.close, s.currency)}</span></span>
      <span class="row__value num">${volume(s.volume)}<small>${changeHtml(s.change_rate, s.country)}</small></span>
    </a></li>`);
}

function loadTopVolume() {
  $("#top-more").href = `/stocks?country=${topCountry}&sort=volume`;
  return load($("#top-volume"), {
    skeleton: skeleton("row", 5),
    fetch: async () => (await Stocks.list({ country: topCountry, sort: "volume", limit: 5 })).items,
    render: (items) => {
      const ul = h('<ul class="list card card--flush"></ul>');
      ul.append(...items.map(volumeRow));
      return ul;
    },
    empty: emptyState({ title: "시세 데이터가 없습니다", body: "데이터 적재 후 다시 확인해 주세요." }),
  });
}

$("#top-tabs").append(segmented([{ value: "KR", label: "국내" }, { value: "US", label: "미국" }], topCountry,
  (v) => { topCountry = v; loadTopVolume(); }, { label: "거래량 상위 시장 선택" }));

function loadAll() {
  loadMarket();
  loadWatchlist();
  loadTopVolume();
}
document.addEventListener(REFRESHED_EVENT, loadAll);
loadAll();
