/**
 * LineChart's y axis: the default ticks are whole dollars of cents, so an empty or few-cent range must still draw
 * distinct ticks (it drew "$0" five times on a 1-cent axis).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { LineChart, xLabelPos } from "@/components/stats/chart";

// The y ticks sit 8px left of the plot (x 64); an edge x label is end-anchored too.
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
    ["Nov 16", 892, 900, { x: 900, textAnchor: "end" }], // a line chart's last tick: centred it ran 16px past the edge
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
