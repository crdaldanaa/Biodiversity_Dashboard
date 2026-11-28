// ECharts sobre tokens del tema: tipografía, ejes recesivos, tooltip de vidrio y resize automático.
/* global echarts */
import { cssVar, fmt, seriesColors } from "../core.js";

export function baseOption({ textColor, gridColor } = {}) {
  const t = textColor || cssVar("--text-2"), g = gridColor || cssVar("--grid-line");
  return {
    backgroundColor: "transparent",
    color: seriesColors(),
    textStyle: { fontFamily: "Inter, system-ui, sans-serif", color: t },
    animationDuration: 700, animationEasing: "cubicOut",
    grid: { left: 48, right: 18, top: 24, bottom: 36, containLabel: true },
    tooltip: {
      backgroundColor: "rgba(10,14,24,.9)", borderColor: "rgba(255,255,255,.14)", borderWidth: 1,
      textStyle: { color: "#f2f4f8", fontSize: 12 }, extraCssText: "backdrop-filter:blur(10px);border-radius:12px;",
      axisPointer: { lineStyle: { color: g }, crossStyle: { color: t } },
    },
    _axis: {
      axisLine: { lineStyle: { color: g } }, axisTick: { show: false },
      splitLine: { lineStyle: { color: g, width: 1 } }, axisLabel: { color: t, fontSize: 11 },
      nameTextStyle: { color: t, fontSize: 11 },
    },
  };
}

export function axis(type, extra = {}) {
  const a = baseOption()._axis;
  // Ejes numéricos en formato es-CO (1.500 y no 1,500) salvo que el panel defina su formatter
  const numFmt = type === "value" || type === "log" ? { formatter: (v) => fmt.d2(v) } : {};
  return { type, ...a, ...extra, axisLabel: { ...a.axisLabel, ...numFmt, ...(extra.axisLabel || {}) } };
}

export function makeChart(el, option) {
  const chart = echarts.init(el, null, { renderer: "canvas" });
  const opt = { ...option };
  delete opt._axis;
  chart.setOption(opt);
  const ro = new ResizeObserver(() => chart.resize());
  ro.observe(el);
  const dispose = chart.dispose.bind(chart);
  chart.dispose = () => { ro.disconnect(); dispose(); };
  return chart;
}
