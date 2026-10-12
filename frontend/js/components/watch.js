// ★ 관심종목 토글 버튼 (낙관적 갱신, 실패 시 원래 상태로)
import { Watchlist } from "../api.js";
import { esc } from "../format.js";
import { icons } from "./icons.js";
import { h, toast } from "./ui.js";

export function starButton(stock, watched) {
  const btn = h('<button class="star" type="button"></button>');
  const paint = (on) => {
    btn.setAttribute("aria-pressed", String(on));
    btn.setAttribute("aria-label", `${stock.name} 관심종목 ${on ? "해제" : "추가"}`);
    btn.innerHTML = on ? icons.starFilled : icons.star;
  };
  let on = watched;
  paint(on);
  btn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !on;
    paint(next);
    btn.disabled = true;
    try {
      if (next) await Watchlist.add(stock.market, stock.ticker);
      else await Watchlist.remove(stock.market, stock.ticker);
      on = next;
      toast(`${esc(stock.name)} 관심종목 ${next ? "추가" : "해제"}`);
    } catch (err) {
      if (err.code === "DUPLICATE_WATCHLIST") on = true;
      else if (err.code === "WATCHLIST_ITEM_NOT_FOUND") on = false;
      else toast(err.message, "error");
      paint(on);
    } finally {
      btn.disabled = false;
    }
  });
  return btn;
}
