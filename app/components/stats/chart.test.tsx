import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { LineChart, linePaths, niceMax, xLabelPos } from "@/components/stats/chart";

const ticks = (c: HTMLElement) => Array.from(c.querySelectorAll("text[text-anchor='end'][x='64']")).map((t) => t.textContent);

describe("LineChart y ticks", () => {
  afterEach(cleanup);

  it("an all-zero cents series draws $0 to $4, not five $0", () => {
    const { container } = render(
      <LineChart labels={["Oct 1", "Oct 2"]} message="" lines={[{ name: "Sales", color: "#3467ff", values: [0, 0] }]} />,
    );
    expect(ticks(container)).toEqual(["$0", "$1", "$2", "$3", "$4"]);
  });

  it("a count axis (own fmt) keeps its 1-unit floor", () => {
    const { container } = render(
      <LineChart labels={["Oct 1", "Oct 2"]} message="" fmt={String}
        lines={[{ name: "Fans", color: "#3467ff", values: [0, 0] }]} />,
    );
    expect(ticks(container)).toEqual(["0", "0.5", "1", "1.5", "2"]);
  });
});

describe("x labels at the chart's edge", () => {
  afterEach(cleanup);

  it.each([
    ["Nov 16", 892, 900, { x: 900, textAnchor: "end" }],
    ["Nov 9", 500, 900, { x: 500, textAnchor: "middle" }],
    ["Oct 19", 72, 900, { x: 72, textAnchor: "middle" }],
  ] as const)("%s at %d of %d", (label, x, W, want) => {
    expect(xLabelPos(label, x, W)).toEqual(want);
  });

  it("LineChart's last label ends at the edge, the rest stay centred", () => {
    const { container } = render(
      <LineChart labels={["Oct 19", "Nov 9", "Nov 16"]} message="" lines={[{ name: "S", color: "#000", values: [1, 2, 3] }]} />,
    );
    const xs = Array.from(container.querySelectorAll("svg text")).filter((t) => /^(Oct|Nov)/.test(t.textContent ?? ""));
    expect(xs.map((t) => t.getAttribute("text-anchor"))).toEqual(["middle", "middle", "end"]);
  });
});

describe("niceMax", () => {
  it.each([
    ["$800,697 a month: $1.2M, not $2M", 80_069_700, 120_000_000],
    ["exact step stays", 40_000_000, 40_000_000],
    ["whole dollars of cents: $4.01 → $8 ($2 steps)", 401, 800],
    ["a sub-1 step keeps 1, 2, 5", 1, 2],
    ["nothing: one per grid line", 0, 4],
  ] as const)("%s", (_name, v, want) => expect(niceMax(v, 4)).toBe(want));
});

describe("partial buckets", () => {
  afterEach(cleanup);
  const at = (i: number) => `${i},0`;
  it("no partial: one solid path, as before", () =>
    expect(linePaths([1, 2, 3], at)).toEqual({ solid: "M0,0 L1,0 L2,0", dashed: "" }));
  it("a short first and last bucket: their segments dashed, the rest solid", () =>
    expect(linePaths([1, 2, 3, 4], at, ["1 of 30 days", undefined, undefined, "2 of 7 days"]))
      .toEqual({ solid: "M1,0 L2,0", dashed: "M0,0 L1,0 M2,0 L3,0" }));
  it("LineChart dashes the last segment and its tooltip says how short", () => {
    const { container } = render(
      <LineChart labels={["Nov 4", "Nov 11", "Nov 18"]} message="" partial={[undefined, undefined, "1 of 7 days"]}
        lines={[{ name: "Tips", color: "#000", values: [5, 6, 1] }]} />,
    );
    expect(container.querySelectorAll("path[data-partial]")).toHaveLength(1);
    const tips = Array.from(container.querySelectorAll("[data-testid='chart-hover'] title")).map((t) => t.textContent);
    expect(tips[2]).toBe("Nov 18 (1 of 7 days)\nTips: 1");
    expect(tips[1]).toBe("Nov 11\nTips: 6");
  });
});
