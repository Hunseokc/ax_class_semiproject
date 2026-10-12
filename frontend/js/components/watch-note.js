// 관심종목 메모·목표가 편집 모달 — PUT /watchlist/{market}/{ticker}
// 비워 두면 그 값을 지운다(null). 목표가는 종목 통화 기준(원 / 달러).
import { Watchlist } from "../api.js";
import { esc, price } from "../format.js";
import { h, openModal, toast } from "./ui.js";

/** w: 관심종목 카드(market, ticker, name, currency, close, memo, target_price) */
export function openWatchNote(w, onSaved) {
  const unit = w.currency === "USD" ? "달러" : "원";
  const form = h(`<form novalidate class="add-form">
      <p class="subtle">${esc(w.name)} · 현재가 ${price(w.close, w.currency)}</p>
      <div class="field"><label for="wn-target">목표가 (${unit})</label>
        <input id="wn-target" class="input num" inputmode="decimal" autocomplete="off" placeholder="비워 두면 목표가 없음"></div>
      <div class="field"><label for="wn-memo">메모 <span class="subtle" data-count></span></label>
        <textarea id="wn-memo" class="input" rows="3" maxlength="200" placeholder="예: 실적 발표 후 다시 보기"></textarea></div>
      <p class="notice notice--warn" data-error hidden></p>
      <div class="modal__foot"><button class="btn" type="button" data-cancel>취소</button>
        <button class="btn btn--primary" type="submit">저장</button></div>
    </form>`);
  const target = form.querySelector("#wn-target");
  const memo = form.querySelector("#wn-memo");
  const count = form.querySelector("[data-count]");
  const errorBox = form.querySelector("[data-error]");
  target.value = w.target_price ?? "";
  memo.value = w.memo ?? "";
  const paintCount = () => { count.textContent = `${memo.value.length}/200`; };
  memo.addEventListener("input", paintCount);
  paintCount();

  const modal = openModal({ title: "메모·목표가", body: form });
  form.querySelector("[data-cancel]").addEventListener("click", () => modal.close());
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorBox.hidden = true;
    const raw = target.value.replace(/[,\s]/g, "");
    const t = raw === "" ? null : Number(raw);
    if (t !== null && !(t > 0)) {
      errorBox.hidden = false;
      errorBox.textContent = "목표가는 0보다 큰 숫자로 입력하세요. 지우려면 비워 두세요.";
      target.focus();
      return;
    }
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      const card = await Watchlist.update(w.market, w.ticker, { target_price: raw === "" ? null : raw, memo: memo.value });
      modal.close();
      toast("메모·목표가를 저장했습니다");
      onSaved?.(card);
    } catch (err) {
      errorBox.hidden = false;
      errorBox.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });
}
