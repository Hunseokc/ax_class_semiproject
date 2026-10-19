// 사이드바(데스크톱) / 하단 탭 바(768px 미만) — 모든 페이지 공통
// 마지막 갱신 시각·새로고침 버튼은 Stage 3(작업별 최신/오래됨 포함), 상단 검색은 Stage 5에서 추가한다.
import { getRefreshStatus, postRefresh } from "../api.js";   // [S3-A]
import { dateTime, esc, relative } from "../format.js";   // [S3-A]
import { icons } from "./icons.js";
import { h, toast } from "./ui.js";   // [S3-A] toast

const NAV = [
  { key: "home", href: "/", label: "대시보드", icon: icons.home },
  { key: "stocks", href: "/stocks", label: "주식 리스트", icon: icons.list },
  { key: "portfolio", href: "/portfolio", label: "모의 포트폴리오", icon: icons.wallet },
  { key: "settings", href: "/settings", label: "설정", icon: icons.settings },
];

export const REFRESHED_EVENT = "market:refreshed";   // [S3-A] 갱신이 끝나면 각 화면이 데이터를 다시 불러오는 신호

// [S3-A] 갱신 작업 이름과 상태(서버 값 → 화면 글자). 색만으로 구분하지 않도록 글자를 함께 쓴다
const JOB_LABELS = { FX: "환율", INDICES: "지수", PRICES: "가격", VALUATION: "밸류에이션" };
const JOB_STATE = { FRESH: "최신", STALE: "오래됨" };

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
        <span class="label">마지막 갱신</span>
        <span class="value" data-refreshed>–</span>
        <div class="basis" data-jobs></div>
        <span class="basis">일봉 기준 · 장중 실시간 아님</span>
        <button class="btn btn--sm" type="button" data-refresh aria-label="시장 데이터 새로고침">${icons.refresh}<span>새로고침</span></button>
      </div>`),
  );
  // ── [S3-A] 마지막 갱신 시각 · 작업별 상태 · 새로고침 버튼 ──
  const label = aside.querySelector("[data-refreshed]");
  const jobs = aside.querySelector("[data-jobs]");
  const btn = aside.querySelector("[data-refresh]");

  const show = (s) => {
    label.textContent = s?.refreshed_at ? `${dateTime(s.refreshed_at)} (${relative(s.refreshed_at)})` : "갱신 기록 없음";
    const next = s?.next_refresh_available_at ? new Date(s.next_refresh_available_at) : null;
    btn.title = next && next > new Date() ? `다음 외부 갱신 가능: ${dateTime(s.next_refresh_available_at)} (그 전에는 저장된 데이터를 다시 확인만 합니다)` : "외부 데이터 갱신";
    jobs.replaceChildren(...(s?.jobs ?? []).filter((j) => JOB_STATE[j.status]).map((j) =>
      h(`<div class="job${j.status === "STALE" ? " job--stale" : ""}">${esc(JOB_LABELS[j.job_type] ?? j.job_type)} · ${JOB_STATE[j.status]}</div>`)));
  };
  getRefreshStatus().then(show).catch(() => { label.textContent = "상태 확인 실패"; });

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    try {
      const r = await postRefresh();
      show(await getRefreshStatus().catch(() => r));   // 갱신 응답의 작업 상태는 SKIPPED 등이라, 최신/오래됨은 상태 조회로 다시 채운다
      getRefreshStatus().then(show).catch(() => {});   // 갱신 응답의 작업 상태는 SKIPPED·FAILED 등이라, 최신/오래됨 표시는 상태 조회로 다시 채운다
      const ran = r.jobs.filter((j) => j.status !== "SKIPPED");
      const failed = r.jobs.filter((j) => ["FAILED", "PARTIAL"].includes(j.status));
      if (failed.length) toast(`일부 갱신 실패: ${failed.map((j) => JOB_LABELS[j.job_type] ?? j.job_type).join(", ")} — 저장된 데이터를 표시합니다`, "error");
      else if (ran.length) toast(`갱신 완료 (${ran.map((j) => JOB_LABELS[j.job_type] ?? j.job_type).join(", ")})`);
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
