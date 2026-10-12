// 사이드바(데스크톱) / 하단 탭 바(768px 미만) — 모든 페이지 공통
// 마지막 갱신 시각·새로고침 버튼은 Stage 3, 상단 검색은 Stage 5에서 추가한다.
import { icons } from "./icons.js";
import { h } from "./ui.js";

const NAV = [
  { key: "home", href: "/", label: "대시보드", icon: icons.home },
  { key: "stocks", href: "/stocks", label: "주식 리스트", icon: icons.list },
  { key: "portfolio", href: "/portfolio", label: "모의 포트폴리오", icon: icons.wallet },
];

export function mountSidebar(active) {
  const aside = document.getElementById("sidebar");
  aside.setAttribute("aria-label", "주 메뉴");
  aside.replaceChildren(
    h('<a class="brand" href="/" aria-label="대시보드 홈"><span class="brand__dots"><i></i><i></i><i></i><i></i></span>StockMind</a>'),
    h(`<nav class="nav">${NAV.map((n) => `
      <a class="nav__item" href="${n.href}" ${n.key === active ? 'aria-current="page"' : ""}>
        <span class="nav__icon-wrap"><span class="nav__icon">${n.icon}</span></span><span>${n.label}</span></a>`).join("")}
    </nav>`),
    h(`<div class="sidebar__foot">
        <span class="basis">일봉 기준 · 장중 실시간 아님</span>
      </div>`),
  );
}
