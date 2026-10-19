// 설정: 화면 테마(라이트 기본 / 다크). 값은 이 브라우저 localStorage에만 두고, 각 HTML head의 인라인 스크립트가 첫 그리기 전에 읽는다.
import { mountSidebar } from "../components/sidebar.js";
import { segmented, toast } from "../components/ui.js";

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
  },
  { label: "화면 테마" },
));
