import { describe, expect, it } from "vitest";
import { BLUE, chartLabels, chartSpecOf, chartTooltip, clearChart, drawChart, tickLabel, tipValue, yScale } from "./ofMirrorChart";

const days = (from: string, n: number, step = 86_400_000) => Array.from({ length: n }, (_, i) => new Date(Date.parse(from) + i * step).toISOString());

describe("OF's chart axes (app.js `z`, `d2`)", () => {
  it("the y step: OF's round steps for the chart's ticks; all zero: steps of 5", () => {
    expect(yScale([0, 0, 0], 3)).toEqual({ step: 5, max: 15 });
    expect(yScale([0, 20, 4], 3)).toEqual({ step: 10, max: 30 });
    expect(yScale([0, 1565], 2)).toEqual({ step: 1000, max: 2000 });
    expect(yScale([0, 4200], 3)).toEqual({ step: 2000, max: 6000 });
  });

  it("tick labels: none at 0; money as $5; a view duration as OF's", () => {
    expect(tickLabel(0, "money")).toBe("");
    expect(tickLabel(5, "money")).toBe("$5");
    expect(tickLabel(1500, "count")).toBe("1,500");
    expect(tickLabel(3600, "duration")).toBe("01h:00m");
  });

  it("tooltip values: money $1,234.00, durations, counts grouped", () => {
    expect(tipValue(1234, "money")).toBe("$1,234.00");
    expect(tipValue(0, "money")).toBe("$0.00");
    expect(tipValue(125, "duration")).toBe("0h:02m");
    expect(tipValue(12000, "count")).toBe("12,000");
  });

  it("labels by the span: hours, hours with the day, days, months; in the owner's time zone", () => {
    expect(chartLabels(days("2026-09-17T00:00:00+00:00", 31), "Europe/Ljubljana")[0]).toBe("Sep 17, 2026");
    expect(chartLabels(days("2026-10-16T10:00:00Z", 25, 3_600_000), "UTC").slice(0, 2)).toEqual(["10:00", "11:00"]);
    expect(chartLabels(days("2026-10-15T00:00:00Z", 49, 3_600_000), "UTC")[0]).toBe("0:00, Oct 15");
    expect(chartLabels(days("2025-01-01T00:00:00Z", 13, 31 * 86_400_000), "UTC")[0]).toBe("Jan, 2025");
    expect(chartLabels([null, "2026-09-17T00:00:00Z", "2026-10-17T00:00:00Z"], "UTC")).toEqual(["", "Sep 17, 2026", "Oct 17, 2026"]);
  });
});

describe("drawChart and its tooltip", () => {
  it("keeps the spec per canvas; the tooltip lists every series of the pair at the point, in OF's markup", () => {
    document.body.innerHTML = `<div class="b-chart"><div class="b-chart__wrapper"><canvas class="b-chart__double-line__main"></canvas></div><div class="b-chart__wrapper"><canvas class="b-chart__double-line__aside"></canvas></div></div>`;
    const [main, aside] = [...document.querySelectorAll("canvas")];
    const labels = ["Sep 17, 2026", "Sep 18, 2026"];
    drawChart(main, { labels, series: { title: "Earnings", values: [0, 12.5], color: BLUE, kind: "money" }, ticks: 3, xLabels: false });
    drawChart(aside, { labels, series: { title: "Subscribers", values: [1, 3], color: "#8a96a3", kind: "count" }, ticks: 2, xLabels: true });
    expect(chartSpecOf(main)!.series.values).toEqual([0, 12.5]);
    expect(main.style.width).toBe("100%");
    const tip = chartTooltip(document, main, 1)!;
    expect(tip.className).toBe("b-chart__tooltip");
    expect(tip.querySelector(".b-chart__tooltip__title")!.textContent!.trim()).toBe("Sep 18, 2026");
    expect([...tip.querySelectorAll(".b-chart__tooltip__text")].map((l) => l.textContent!.replace(/\s+/g, " ").trim())).toEqual(["Earnings $12.50", "Subscribers 3"]);
    clearChart(main);
    expect(chartSpecOf(main)).toBeUndefined();
    expect(document.querySelector("[data-oi-chart-tip]")).toBeNull();
  });
});
