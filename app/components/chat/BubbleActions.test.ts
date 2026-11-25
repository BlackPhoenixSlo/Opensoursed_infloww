import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fmtSent } from "@/components/chat/BubbleActions";

const pick = (d: Date, opts: Intl.DateTimeFormatOptions, types: string[]) =>
  new Intl.DateTimeFormat([], opts).formatToParts(d).filter((p) => types.includes(p.type)).map((p) => p.value);
const parts = (d: Date) => [
  ...pick(d, { year: "numeric", day: "numeric" }, ["year", "day"]),
  ...pick(d, { hour: "numeric", minute: "2-digit" }, ["minute"]),
];

describe("fmtSent", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 15, 14, 0));
  });
  afterEach(() => vi.useRealTimers());

  it.each([undefined, "", "nope", "2026-13-45T99:00:00Z"])("%j → —", (iso) => {
    expect(fmtSent(iso)).toBe("—");
  });

  it.each([
    ["same day",   [2026, 9, 15, 9, 47]],
    ["yesterday",  [2026, 9, 14, 23, 59]],
    ["last year",  [2025, 2, 3, 7, 38]],
  ] as const)("%s → date and time", (_l, [y, m, day, h, min]) => {
    const d = new Date(y, m, day, h, min);
    const out = fmtSent(d.toISOString());
    expect(out).not.toBe("—");
    const want = parts(d);
    expect(want).toHaveLength(3);
    for (const p of want) expect(out).toContain(p);
  });
});
