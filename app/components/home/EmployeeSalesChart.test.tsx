/**
 * Employee sales' x labels: one per 65px of plot, counted back from the newest day so it is always named (a phone's
 * 30 days read Oct 20, Oct 30, Nov 9 and never reached Nov 18).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { EmployeeSalesChart, labelled } from "@/components/home/EmployeeSalesChart";

describe("labelled", () => {
  it.each([
    ["phone, 30 days: the last day, then every 10th back", 30, 220, [9, 19, 29]],
    ["desktop, 30 days: every 3rd back from the last", 30, 837, [2, 5, 8, 11, 14, 17, 20, 23, 26, 29]],
    ["7 days with room: every day", 7, 837, [0, 1, 2, 3, 4, 5, 6]],
    ["one day", 1, 220, [0]],
    ["none", 0, 220, []],
  ] as const)("%s", (_name, n, w, want) => expect(labelled(n, w)).toEqual(want));
});

describe("EmployeeSalesChart", () => {
  afterEach(cleanup);
  it("names the last day, end-anchored at the chart's edge", () => {
    const points = Array.from({ length: 30 }, (_, i) => ({
      start: new Date(Date.UTC(2026, 9, 20 + i)).toISOString().slice(0, 10),
      revenue_cents: 100 * i, messages_cents: 0, tips_cents: 0,
    }));
    const { container } = render(<EmployeeSalesChart points={points} />);
    const xs = Array.from(container.querySelectorAll("text")).filter((t) => /^(Oct|Nov) /.test(t.textContent ?? ""));
    expect(xs.at(-1)?.textContent).toBe("Nov 18");
    expect(xs.at(-1)?.getAttribute("text-anchor")).toBe("end");
  });
});
