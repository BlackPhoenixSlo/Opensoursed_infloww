/**
 * The reports' export helpers: sections flattened to one sheet, cents as dollars and the by-day reads' concurrency
 * cap.
 */
import { describe, expect, it } from "vitest";

import { mapLimit, sectionsToRows, usd } from "@/lib/reportExport";

describe("sectionsToRows", () => {
  it("writes a lone section as its rows, several under their titles with a blank line between", () => {
    const total = { title: "Total", rows: [["Creator", "Total earnings"], ["Ann", 12.5]] };
    const day = { title: "By day", rows: [["Day", "Creator"], ["2026-10-01", "Ann"]] };
    expect(sectionsToRows([total])).toEqual(total.rows);
    expect(sectionsToRows([total, day])).toEqual([
      ["Total"], ["Creator", "Total earnings"], ["Ann", 12.5], [], ["By day"], ["Day", "Creator"], ["2026-10-01", "Ann"],
    ]);
  });
});

describe("usd", () => {
  it("is dollars to the cent, a number", () => {
    expect(usd(1234)).toBe(12.34);
    expect(usd(-50)).toBe(-0.5);
    expect(usd(1234.6)).toBe(12.35);
  });
});

describe("mapLimit", () => {
  it("runs at most `limit` at a time and keeps the order", async () => {
    let running = 0;
    let peak = 0;
    const out = await mapLimit([5, 1, 4, 2, 3], 2, async (n) => {
      running++;
      peak = Math.max(peak, running);
      await new Promise((r) => setTimeout(r, n));
      running--;
      return n * 10;
    });
    expect(out).toEqual([50, 10, 40, 20, 30]);
    expect(peak).toBe(2);
    expect(await mapLimit([], 4, async (n: number) => n)).toEqual([]);
  });
});
