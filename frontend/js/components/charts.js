// Chart.js(CDN, window.Chart) 공통 설정과 차트 헬퍼.
// 레퍼런스: 둥근 막대 + 점선 기준선 + 흰색 툴팁, 얇은 스파크라인.
const Chart = window.Chart;
const css = getComputedStyle(document.documentElement);
export const color = (name) => css.getPropertyValue(name).trim();

if (Chart) {
  Chart.defaults.font.family = color("--font") || "Plus Jakarta Sans, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = color("--text-3");
  Chart.defaults.borderColor = color("--line");
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: color("--tooltip-bg"), titleColor: color("--tooltip-text"), bodyColor: color("--tooltip-text"),
    padding: 10, cornerRadius: 12, displayColors: false,
    titleFont: { weight: "700" }, bodyFont: { weight: "600" },
  });
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.animation.duration = 400;
}

const registry = new WeakMap();

/** 같은 canvas에 다시 그릴 때 이전 차트를 정리한다 */
export function draw(canvas, config) {
  registry.get(canvas)?.destroy();
  if (!Chart) {
    canvas.replaceWith(Object.assign(document.createElement("p"), { className: "subtle", textContent: "차트 라이브러리를 불러오지 못했습니다." }));
    return null;
  }
  const chart = new Chart(canvas, config);
  registry.set(canvas, chart);
  return chart;
}

/** root 안 canvas의 차트를 정리한다 — 카드를 통째로 다시 그리기 전에 호출(Chart.js 인스턴스 누적 방지) */
export function destroyCharts(root) {
  root.querySelectorAll("canvas").forEach((c) => { registry.get(c)?.destroy(); registry.delete(c); });
}

/** 스파크라인: 축·툴팁 없는 얇은 선 */
export function sparkline(canvas, values, stroke = color("--ice")) {
  return draw(canvas, {
    type: "line",
    data: { labels: values.map((_, i) => i), datasets: [{ data: values, borderColor: stroke, borderWidth: 2, pointRadius: 0, tension: 0.35, fill: false }] },
    options: {
      responsive: true, maintainAspectRatio: false, events: [],
      scales: { x: { display: false }, y: { display: false } },
      plugins: { tooltip: { enabled: false } },
    },
  });
}

/** 점선 기준선 축 옵션 (Chart.js v4: 격자선 점선은 border.dash) */
export const dashedAxis = { grid: { color: color("--line"), drawTicks: false }, border: { display: false, dash: [4, 4] } };
export const plainAxis = { grid: { display: false }, border: { display: false } };

// ── [S4-A] 매력도 점수 뱃지·구간·미니 게이지 ──
// TODO(D가 ui.js로 이동): 원본은 components/ui.js에 있다. ui.js는 D 소유라 A 담당인 이 파일에 두었다 (이름·동작은 원본 그대로)
export function scoreBadge(score) {
  return score === null || score === undefined
    ? '<span class="score score--none" title="매력도 데이터 부족">–</span>'
    : `<span class="score" title="매력도 백분위 ${Math.round(score)} — 같은 시장 상위 ${Math.max(1, Math.ceil(100 - score))}% (투자 권유 아님)">${Math.round(score)}</span>`;
}

// ---------------------------------------------------------------- 매력도 미니 게이지 (관심종목 카드)
const BANDS = ["매우 낮음", "낮음", "보통", "높음", "매우 높음"];

/** 0~100 점수 → 5구간 {index 1~5, label}. 점수가 없으면 null */
export function scoreBand(score) {
  if (score === null || score === undefined) return null;
  const i = Math.min(4, Math.floor(Math.max(0, score) / 20));
  return { index: i + 1, label: BANDS[i] };
}

const GX = 46, GY = 48, GR = 36;
const gp = (deg) => `${(GX + GR * Math.cos((deg * Math.PI) / 180)).toFixed(2)} ${(GY - GR * Math.sin((deg * Math.PI) / 180)).toFixed(2)}`;
const garc = (from, to) => `M ${gp(from)} A ${GR} ${GR} 0 0 1 ${gp(to)}`;

/** 반원 게이지: 5구간(테라코타~청록, 현재 구간만 진하게) + 바늘 + 점수·구간 라벨. 점수 없으면 점선 + '데이터 부족'
 *  labels: 구간 라벨 5개(기본 매력도 '매우 낮음'~'매우 높음') — 시장 심리 지수처럼 다른 의미로 쓸 때 바꾼다 */
export function scoreGauge(score, { labels = BANDS } = {}) {
  const band = scoreBand(score);
  if (!band) {
    return `<div class="gauge-mini gauge-mini--na">
        <svg viewBox="0 0 92 54" aria-hidden="true"><path class="gauge-mini__ticks" d="${garc(180, 0)}"/></svg>
        <div class="gauge-mini__value"><strong>–</strong><span class="gauge-mini__band"><i class="gauge-mini__ring"></i>데이터 부족</span></div>
      </div>`;
  }
  const segs = BANDS.map((_, i) => `<path d="${garc(180 - i * 36 - 1.5, 180 - (i + 1) * 36 + 1.5)}"
      stroke="var(--gauge-${i + 1})" opacity="${i + 1 === band.index ? 1 : 0.3}"/>`).join("");
  const angle = Math.max(0, Math.min(100, score)) * 1.8 - 90;
  return `<div class="gauge-mini">
      <svg viewBox="0 0 92 54" aria-hidden="true"><g class="gauge-mini__arc">${segs}</g>
        <g class="gauge-mini__needle" style="transform:rotate(${angle.toFixed(1)}deg)">
          <line x1="${GX}" y1="${GY}" x2="${GX}" y2="${GY - 29}"/><circle cx="${GX}" cy="${GY}" r="3.5"/></g></svg>
      <div class="gauge-mini__value"><strong class="num">${Math.round(score)}</strong>
        <span class="gauge-mini__band"><i style="background:var(--gauge-${band.index})"></i>${labels[band.index - 1]}</span></div>
    </div>`;
}
