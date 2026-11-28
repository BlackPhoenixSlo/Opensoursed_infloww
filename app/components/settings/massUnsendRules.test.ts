import { describe, expect, it } from "vitest";

import type { MassMessageRow } from "@/hooks/useMassMessages";
import {
  BULK_MIN_AGE_H,
  bulkCounts,
  bulkTargets,
  isActionable,
  isFreeTextOld,
  olderThanHours,
  visibleMassRows,
  unsendByCreator,
  type ActionableRow,
  type BulkAction,
} from "./massUnsendRules";

const NOW = Date.parse("2026-10-31T12:00:00Z");
const H = 3_600_000;
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const OLD = ago(5 * H);

const row = (id: number, over: Partial<MassMessageRow> = {}): MassMessageRow => ({
  id, date: OLD, isFree: true, mediaCount: 0, canUnsend: true, isCanceled: false, __accountId: "a", ...over,
});

describe("olderThanHours (the 4 h age gate)", () => {
  it.each([
    ["exactly 4 h", ago(4 * H), true],
    ["1 ms under 4 h", ago(4 * H - 1), false],
    ["5 h", ago(5 * H), true],
    ["in the future", ago(-H), false],
    ["no date", null, false],
    ["empty date", "", false],
    ["bad date", "not a date", false],
  ])("%s -> %s", (_label, date, want) => {
    expect(olderThanHours(row(1, { date }), BULK_MIN_AGE_H, NOW)).toBe(want);
  });
});

describe("isFreeTextOld", () => {
  it.each([
    ["free text, old", {}, true],
    ["free GIF-only, old (a GIF is not an image)", { giphyId: "g1" }, true],
    ["free with an image", { mediaCount: 1 }, false],
    ["paid text", { isFree: false }, false],
    ["isFree missing", { isFree: undefined }, false],
    ["free text, fresh", { date: ago(H) }, false],
  ] as const)("%s -> %s", (_label, over, want) => {
    expect(isFreeTextOld(row(1, over as Partial<MassMessageRow>), NOW)).toBe(want);
  });
});

describe("isActionable", () => {
  it.each([
    ["live", {}, true],
    ["already unsent", { isCanceled: true }, false],
    ["canUnsend false", { canUnsend: false }, false],
    ["canUnsend missing", { canUnsend: undefined }, false],
    ["no accountId", { __accountId: undefined }, false],
  ] as const)("%s -> %s", (_label, over, want) => {
    expect(isActionable(row(1, over as Partial<MassMessageRow>))).toBe(want);
  });
});

const ROWS: MassMessageRow[] = [
  row(1),
  row(2, { giphyId: "g" }),
  row(3, { mediaCount: 2 }),
  row(4, { isFree: false }),
  row(5, { isFree: false, mediaCount: 1 }),
  row(6, { date: ago(4 * H) }),
  row(7, { date: ago(4 * H - 1) }),
  row(8, { date: null }),
  row(9, { date: "garbage" }),
  row(10, { mediaCount: 1, date: ago(H) }),
  row(11, { isCanceled: true }),
  row(12, { canUnsend: false }),
  row(13, { __accountId: undefined }),
  row(21, { __accountId: "b" }),
  row(22, { __accountId: "b", mediaCount: 1 }),
  row(23, { __accountId: "b", date: ago(H) }),
  row(24, { __accountId: "b", isCanceled: true }),
];
const ids = (rs: MassMessageRow[]) => rs.map((r) => r.id);

describe("bulkTargets: the rows a bulk unsend picks", () => {
  it.each<[string, string[], BulkAction, number[]]>([
    ["all models, Unsend all", [], "all", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 21, 22, 23]],
    ["all models, non-image", [], "non-image", [1, 2, 4, 6, 21]],
    ["all models, with images", [], "with-image", [3, 5, 22]],
    ["all models, free text", [], "free-text-old", [1, 2, 6, 21]],
    ["chip a, Unsend all", ["a"], "all", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]],
    ["chip a, non-image", ["a"], "non-image", [1, 2, 4, 6]],
    ["chip a, with images", ["a"], "with-image", [3, 5]],
    ["chip a, free text", ["a"], "free-text-old", [1, 2, 6]],
    ["chip b, Unsend all", ["b"], "all", [21, 22, 23]],
    ["chip b, free text", ["b"], "free-text-old", [21]],
    ["chip b, with images", ["b"], "with-image", [22]],
    ["chips a + b, free text", ["a", "b"], "free-text-old", [1, 2, 6, 21]],
    ["chip of a model with no rows", ["c"], "all", []],
  ])("%s", (_label, chips, action, want) => {
    expect(ids(bulkTargets(ROWS, new Set(chips), action, NOW))).toEqual(want);
  });

  it("never picks an unsent, un-unsendable or Creator-less row, whatever the action", () => {
    for (const action of ["all", "non-image", "with-image", "free-text-old"] as const) {
      const got = ids(bulkTargets(ROWS, new Set(), action, NOW));
      for (const bad of [11, 12, 13, 24]) expect(got).not.toContain(bad);
    }
  });

  it("is the same rows the age gate lets through as time moves: row 7 joins 1 ms later", () => {
    expect(ids(bulkTargets(ROWS, new Set(["a"]), "free-text-old", NOW + 1))).toEqual([1, 2, 6, 7]);
  });
});

describe("bulkCounts", () => {
  it.each<[string[], Record<BulkAction, number>]>([
    [[], { all: 13, "non-image": 5, "with-image": 3, "free-text-old": 4 }],
    [["b"], { all: 3, "non-image": 1, "with-image": 1, "free-text-old": 1 }],
  ])("chips %j", (chips, want) => {
    expect(bulkCounts(ROWS, new Set(chips), NOW)).toEqual(want);
  });
});

describe("a Fansly broadcast row (string id, canUnsend: false)", () => {
  const fansly = (id: string): MassMessageRow =>
    ({ ...row(0), id, canUnsend: false, unsendSeconds: 0, isTip: false, __accountId: "f" });
  const FANSLY = [fansly("900539700124344321"), fansly("900539700124344322")];

  it("is not actionable", () => {
    expect(FANSLY.map(isActionable)).toEqual([false, false]);
  });

  it("is never a bulk target and adds nothing to the counts", () => {
    for (const action of ["all", "non-image", "with-image", "free-text-old"] as const) {
      expect(bulkTargets([...ROWS, ...FANSLY], new Set(), action, NOW).map((r) => r.id)).toEqual(
        bulkTargets(ROWS, new Set(), action, NOW).map((r) => r.id));
      expect(bulkTargets(FANSLY, new Set(["f"]), action, NOW)).toEqual([]);
    }
    expect(bulkCounts([...ROWS, ...FANSLY], new Set(), NOW)).toEqual({ all: 13, "non-image": 5, "with-image": 3, "free-text-old": 4 });
  });

  it("two adjacent big ids stay two listed rows", () => {
    expect(ids(visibleMassRows(FANSLY, new Set(["f"]), true))).toEqual(["900539700124344321", "900539700124344322"]);
  });
});

describe("visibleMassRows", () => {
  it.each<[string, string[], boolean, MassMessageRow["id"][]]>([
    ["all, unsent hidden", [], true, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 21, 22, 23]],
    ["all, unsent shown", [], false, ids(ROWS)],
    ["chip b, unsent hidden", ["b"], true, [21, 22, 23]],
    ["chip b, unsent shown", ["b"], false, [21, 22, 23, 24]],
  ])("%s", (_label, chips, hide, want) => {
    expect(ids(visibleMassRows(ROWS, new Set(chips), hide))).toEqual(want);
  });
});

describe("unsendByCreator", () => {
  const row = (id: number, acc: string) => ({ id, __accountId: acc } as unknown as ActionableRow);

  it("runs one delete at a time, each Creator's as a block in first-listed order, and counts failures", async () => {
    let inFlight = 0;
    let peak = 0;
    const order: MassMessageRow["id"][] = [];
    const failed = await unsendByCreator(
      [row(1, "a"), row(2, "b"), row(3, "a"), row(4, "c"), row(5, "b")],
      async (r) => {
        peak = Math.max(peak, ++inFlight);
        order.push(r.id);
        await new Promise((res) => setTimeout(res, 1));
        inFlight -= 1;
        if (r.id === 3 || r.id === 4) throw new Error("OF said no");
      },
    );
    expect(peak).toBe(1);
    expect(order).toEqual([1, 3, 2, 5, 4]);
    expect(failed).toBe(2);
  });

  it("reports progress after each delete, failures included", async () => {
    const ticks: string[] = [];
    let inFlight = 0;
    await unsendByCreator(
      [row(1, "a"), row(2, "b"), row(3, "a")],
      async (r) => {
        inFlight += 1;
        await new Promise((res) => setTimeout(res, 1));
        inFlight -= 1;
        if (r.id === 2) throw new Error("OF said no");
      },
      (done, total) => ticks.push(`${done}/${total}:${inFlight}`),
    );
    expect(ticks).toEqual(["1/3:0", "2/3:0", "3/3:0"]);
  });

  it("nothing to unsend: no calls, no failures", async () => {
    let calls = 0;
    expect(await unsendByCreator([], async () => { calls += 1; })).toBe(0);
    expect(calls).toBe(0);
  });
});
