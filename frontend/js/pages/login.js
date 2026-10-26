// 로그인 / 회원가입 (2차). 성공하면 ?next= 주소(같은 사이트 경로만)나 홈으로 돌아간다.
// 가입(이메일·Google 처음)하면 지금 브라우저의 게스트 관심종목이 계정으로 옮겨진다(서버가 처리).
// Google 버튼은 서버에 GOOGLE_CLIENT_ID가 있을 때만 Google Identity Services 스크립트를 불러 그린다.
import { getAuthConfig, googleLogin, isLoggedIn, loadPrefs, login, signup } from "../api.js";
import { mountSidebar } from "../components/sidebar.js";
import { segmented } from "../components/ui.js";

mountSidebar("settings");
const form = document.getElementById("auth-form");
const title = document.querySelector("[data-title]");
const submit = form.querySelector("[data-submit]");
const error = form.querySelector("[data-error]");
const raw = new URLSearchParams(location.search).get("next") || "/";
const next = raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/login") ? raw : "/";
const GSI_SRC = "https://accounts.google.com/gsi/client";
let mode = "login";

const MODES = {
  login: { label: "로그인", password: "current-password" },
  signup: { label: "회원가입", password: "new-password" },
};

function setMode(m) {
  mode = m;
  title.textContent = MODES[m].label;
  submit.textContent = MODES[m].label;
  form.password.autocomplete = MODES[m].password;
  form.querySelectorAll("[data-signup]").forEach((el) => { el.hidden = m !== "signup"; });
  error.hidden = true;
}

function showError(message) {
  error.textContent = message;
  error.hidden = false;
}

async function done() {
  await loadPrefs({ force: true }).catch(() => {});   // 계정에 저장한 설정을 이 브라우저로
  location.assign(next);
}

document.getElementById("auth-tabs").replaceChildren(segmented(
  [{ value: "login", label: "로그인" }, { value: "signup", label: "회원가입" }], mode, setMode, { label: "로그인 또는 회원가입" }));

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = form.email.value.trim();
  const password = form.password.value;
  const nickname = form.nickname.value.trim();
  if (!email || !password) return showError("이메일과 비밀번호를 입력해 주세요");
  if (mode === "signup" && password.length < 8) return showError("비밀번호는 8자 이상이어야 해요");
  if (mode === "signup" && nickname.length < 2) return showError("닉네임은 2자 이상이어야 해요");
  submit.disabled = true;
  try {
    if (mode === "login") await login(email, password);
    else await signup(email, password, nickname);
    await done();
  } catch (err) {
    // 형식 오류(422)는 칸별 메시지가 영어라 우리말 한 줄로 바꿔 보여 준다
    showError(err.code === "VALIDATION_ERROR" ? "입력한 값의 형식을 확인해 주세요 (이메일 형식, 닉네임 글자)" : err.message);
  } finally {
    submit.disabled = false;
  }
});

// ---------------------------------------------------------------- Google 로그인
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = Object.assign(document.createElement("script"), { src, async: true, onload: resolve, onerror: reject });
    document.head.append(s);
  });
}

async function mountGoogle() {
  const { google_client_id: clientId } = await getAuthConfig();
  if (!clientId) return;
  await loadScript(GSI_SRC);
  const box = document.querySelector("[data-google]");
  box.hidden = false;
  window.google.accounts.id.initialize({
    client_id: clientId,
    callback: async ({ credential }) => {
      try {
        await googleLogin(credential);
        await done();
      } catch (err) { showError(err.message); }
    },
  });
  const theme = document.documentElement.dataset.theme === "light" ? "outline" : "filled_black";
  window.google.accounts.id.renderButton(box.querySelector("[data-google-button]"),
    { theme, size: "large", shape: "pill", text: "continue_with", locale: "ko", width: 280 });
}

if (isLoggedIn()) location.replace(next);
else mountGoogle().catch(() => { /* Google 스크립트를 못 불러오면 이메일 로그인만 */ });
