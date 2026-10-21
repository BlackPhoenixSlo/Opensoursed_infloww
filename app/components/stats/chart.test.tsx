/**
 * LineChart's y axis: the default ticks are whole dollars of cents, so an empty or few-cent range must still draw
 * distinct ticks (it drew "$0" five times on a 1-cent axis).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { LineChart } from "@/components/stats/chart";

const ticks = (c: HTMLElement) => Array.from(c.querySelectorAll("text[text-anchor='end']")).map((t) => t.textContent);

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
