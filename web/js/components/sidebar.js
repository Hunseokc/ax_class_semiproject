// 사이드바(데스크톱) / 하단 탭 바(768px 미만) + 마지막 갱신 시각·새로고침
import { Market } from "../api.js";
import { dateTime, relative } from "../format.js";
import { icons } from "./icons.js";
import { h, toast } from "./ui.js";

const NAV = [
  { key: "home", href: "/", label: "대시보드", icon: icons.home },
  { key: "stocks", href: "/stocks", label: "주식 리스트", icon: icons.list },
  { key: "portfolio", href: "/portfolio", label: "모의 포트폴리오", icon: icons.wallet },
];

export const REFRESHED_EVENT = "market:refreshed";

export function mountSidebar(active) {
  const aside = document.getElementById("sidebar");
  aside.setAttribute("aria-label", "주 메뉴");
  aside.replaceChildren(
    h('<a class="brand" href="/" aria-label="대시보드 홈"><span class="brand__dots"><i></i><i></i><i></i><i></i></span>Stock Board</a>'),
    h(`<nav class="nav">${NAV.map((n) => `
      <a class="nav__item" href="${n.href}" ${n.key === active ? 'aria-current="page"' : ""}>
        <span class="nav__icon-wrap"><span class="nav__icon">${n.icon}</span></span><span>${n.label}</span></a>`).join("")}
    </nav>`),
    h(`<div class="sidebar__foot">
        <span class="label">마지막 갱신</span>
        <span class="value" data-refreshed>–</span>
        <span class="basis">일봉 기준 · 장중 실시간 아님</span>
        <button class="btn btn--sm" type="button" data-refresh aria-label="시장 데이터 새로고침">${icons.refresh}<span>새로고침</span></button>
      </div>`),
  );
  const label = aside.querySelector("[data-refreshed]");
  const btn = aside.querySelector("[data-refresh]");

  const show = (s) => {
    label.textContent = s?.refreshed_at ? `${dateTime(s.refreshed_at)} (${relative(s.refreshed_at)})` : "갱신 기록 없음";
    const next = s?.next_refresh_available_at ? new Date(s.next_refresh_available_at) : null;
    btn.title = next && next > new Date() ? `다음 외부 갱신 가능: ${dateTime(s.next_refresh_available_at)} (그 전에는 저장된 데이터를 다시 확인만 합니다)` : "외부 데이터 갱신";
  };
  Market.status().then(show).catch(() => { label.textContent = "상태 확인 실패"; });

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    try {
      const r = await Market.refresh();
      show(r);
      const ran = r.jobs.filter((j) => !["SKIPPED"].includes(j.status));
      const failed = r.jobs.filter((j) => ["FAILED", "PARTIAL"].includes(j.status));
      if (failed.length) toast(`일부 갱신 실패: ${failed.map((j) => j.job_type).join(", ")} — 저장된 데이터를 표시합니다`, "error");
      else if (ran.length) toast(`갱신 완료 (${ran.map((j) => j.job_type).join(", ")})`);
      else toast(`이미 최신입니다. 다음 갱신 가능: ${dateTime(r.next_refresh_available_at)}`);
      document.dispatchEvent(new CustomEvent(REFRESHED_EVENT, { detail: r }));
    } catch (e) {
      toast(e.message, "error");
    } finally {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
    }
  });
}
