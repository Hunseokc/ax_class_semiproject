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
    backgroundColor: "#ffffff", titleColor: "#141414", bodyColor: "#141414",
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
