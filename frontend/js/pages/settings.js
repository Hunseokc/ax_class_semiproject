// 설정: 화면 테마(라이트 기본 / 다크)와 계정(2차 로그인). 값은 이 브라우저 localStorage에만 두고, 각 HTML head의 인라인 스크립트가 첫 그리기 전에 읽는다.
import { changePassword, getMe, isLoggedIn, logoutAll, savePref, withdraw } from "../api.js";   // 2차 로그인
import { mountSidebar } from "../components/sidebar.js";
import { h, openModal, segmented, toast } from "../components/ui.js";

mountSidebar("settings");
const KEY = "stockmind:theme";
const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";

document.getElementById("theme").replaceChildren(segmented(
  [{ value: "dark", label: "다크" }, { value: "light", label: "라이트" }],
  current,
  (theme) => {
    if (theme === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem(KEY, theme); } catch { toast("이 브라우저에서는 설정을 저장할 수 없어 이번 화면에만 적용됩니다", "error"); }
    savePref("theme");   // 2차 로그인: 계정에도 저장
  },
  { label: "화면 테마" },
));

// ── 2차 로그인: 계정 (로그인 안내 / 비밀번호 변경·설정 · 모든 기기 로그아웃 · 탈퇴) ──
// 로그인하면 이 화면의 테마 같은 설정이 계정에도 저장돼 다른 기기에서 이어진다
const desc = document.querySelector("[data-account-desc]");
const account = document.getElementById("account");

function renderLoggedOut() {
  desc.textContent = "로그인하면 관심종목·포트폴리오·설정을 다른 기기에서도 그대로 볼 수 있어요. 로그인하지 않은 관심종목은 3일 동안 들어오지 않으면 지워져요.";
  account.replaceChildren(h('<a class="btn btn--primary" href="/login?next=/settings">로그인 · 회원가입</a>'));
}

function passwordForm(me) {
  const form = h(`<form novalidate aria-label="${me.has_password ? "비밀번호 변경" : "비밀번호 설정"}">
      ${me.has_password ? `<div class="field"><label for="pw-current">지금 비밀번호</label>
        <input class="input" id="pw-current" type="password" autocomplete="current-password" maxlength="128"></div>` : ""}
      <div class="field"><label for="pw-new">새 비밀번호 (8자 이상)</label>
        <input class="input" id="pw-new" type="password" autocomplete="new-password" maxlength="128"></div>
      <button class="btn" type="submit">${me.has_password ? "비밀번호 변경" : "비밀번호 설정"}</button></form>`);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const cur = form.querySelector("#pw-current")?.value || null;
    const nw = form.querySelector("#pw-new").value;
    if (nw.length < 8) return toast("새 비밀번호는 8자 이상이어야 해요", "error");
    try {
      await changePassword(cur, nw);
      toast(me.has_password ? "비밀번호를 바꿨어요. 다른 기기는 로그아웃됐어요" : "비밀번호를 정했어요. 이제 이메일로도 로그인할 수 있어요");
      if (!me.has_password) location.reload();
      form.reset();
    } catch (err) { toast(err.message, "error"); }
  });
  return form;
}

function openWithdraw(me) {
  const body = h(`<form novalidate>
      <p>관심종목·포트폴리오·설정까지 모두 지워지고 되돌릴 수 없어요.${me.has_password ? " 계속하려면 비밀번호를 입력해 주세요." : ""}</p>
      ${me.has_password ? `<div class="field"><label for="wd-pw">비밀번호</label>
        <input class="input" id="wd-pw" type="password" autocomplete="current-password" maxlength="128"></div>` : ""}
      <div class="modal__foot"><button class="btn btn--danger" type="submit">탈퇴하기</button></div></form>`);
  const { close } = openModal({ title: "탈퇴", body });
  body.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await withdraw(body.querySelector("#wd-pw")?.value || null);
      close();
      location.assign("/");
    } catch (err) { toast(err.message, "error"); }
  });
}

function renderAccount(me) {
  desc.textContent = `${me.nickname} · ${me.email}${me.has_google ? " · Google 연결됨" : ""}`;
  const actions = h(`<div class="settings__actions">
      <button class="btn" type="button" data-logout-all>모든 기기에서 로그아웃</button>
      <button class="btn btn--danger" type="button" data-withdraw>탈퇴</button></div>`);
  actions.querySelector("[data-logout-all]").addEventListener("click", async () => {
    try { await logoutAll(); location.reload(); } catch (err) { toast(err.message, "error"); }
  });
  actions.querySelector("[data-withdraw]").addEventListener("click", () => openWithdraw(me));
  account.replaceChildren(passwordForm(me), actions);
}

if (!isLoggedIn()) renderLoggedOut();
else getMe().then((me) => (me.logged_in ? renderAccount(me) : renderLoggedOut())).catch(renderLoggedOut);
