/** scheduleHistory: the per-scope pick log, the local datetime helpers, and the next-slot prediction.
 *  The suite pins no TZ, so every row builds times from local fields and asserts local fields (July: no DST edge). */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  describePrediction, loadHistory, localDatetimeToIso, predictNext, recordSchedule, toLocalDatetimeInput,
  type HistoryEntry, type Prediction,
} from "./scheduleHistory";

const KEY = "chatterly:schedule:history:";
/** Local wall-clock time, July 2026. */
const at = (day: number, h: number, m = 0) => new Date(2026, 6, day, h, m);
const v = (day: number, h: number, m = 0) => toLocalDatetimeInput(at(day, h, m));
const entry = (value: string, savedAt = 0): HistoryEntry => ({ value, savedAt });

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

describe("loadHistory", () => {
  it.each([
    ["nothing stored", undefined, []],
    ["corrupt JSON", "{not json", []],
    ["not an array", '{"value":"2026-07-10T09:00","savedAt":1}', []],
    ["bad entries filtered", JSON.stringify([
      null, 5, { value: "2026-07-10", savedAt: 1 }, { value: "2026-07-10T09:00" }, { value: "2026-07-10T09:00", savedAt: 2 },
    ]), [entry("2026-07-10T09:00", 2)]],
  ])("%s", (_, raw, want) => {
    if (raw !== undefined) localStorage.setItem(KEY + "acct", raw);
    expect(loadHistory("acct")).toEqual(want);
  });

  it("null, undefined and '' scopes share the default key", () => {
    localStorage.setItem(KEY + "default", JSON.stringify([entry("2026-07-10T09:00", 1)]));
    for (const s of [null, undefined, ""]) expect(loadHistory(s)).toEqual([entry("2026-07-10T09:00", 1)]);
    expect(loadHistory("acct")).toEqual([]);
  });
});

describe("recordSchedule", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(at(1, 12));
  });

  it("pushes newest first, stamped with now", () => {
    recordSchedule("a", v(10, 9));
    vi.setSystemTime(at(2, 12));
    recordSchedule("a", v(11, 9));
    expect(loadHistory("a")).toEqual([entry(v(11, 9), at(2, 12).getTime()), entry(v(10, 9), at(1, 12).getTime())]);
  });

  it("dedupes only against the most recent pick", () => {
    recordSchedule("a", v(10, 9));
    recordSchedule("a", v(10, 9));
    expect(loadHistory("a").map((e) => e.value)).toEqual([v(10, 9)]);
    recordSchedule("a", v(11, 9));
    recordSchedule("a", v(10, 9));
    expect(loadHistory("a").map((e) => e.value)).toEqual([v(10, 9), v(11, 9), v(10, 9)]);
  });

  it("caps at 8, dropping the oldest", () => {
    for (let d = 1; d <= 10; d++) recordSchedule("a", v(d, 9));
    expect(loadHistory("a").map((e) => e.value)).toEqual([10, 9, 8, 7, 6, 5, 4, 3].map((d) => v(d, 9)));
  });

  it("ignores short values and keeps scopes apart", () => {
    recordSchedule("a", "2026-07-10");
    recordSchedule(null, v(10, 9));
    expect(loadHistory("a")).toEqual([]);
    expect(loadHistory(null).map((e) => e.value)).toEqual([v(10, 9)]);
  });
});

describe("toLocalDatetimeInput / localDatetimeToIso", () => {
  it("formats local fields, zero-padded", () => {
    expect(toLocalDatetimeInput(new Date(2026, 0, 5, 7, 3, 59))).toBe("2026-01-05T07:03");
  });

  it.each(["2026-07-10T09:30", "2026-01-05T00:00", "2026-12-31T23:59"])("%s round-trips", (s) => {
    const iso = localDatetimeToIso(s)!;
    expect(iso).toMatch(/Z$/);
    expect(toLocalDatetimeInput(new Date(iso))).toBe(s);
  });

  it("keeps seconds", () => {
    const d = new Date(localDatetimeToIso("2026-07-10T09:30:45")!);
    expect([d.getHours(), d.getMinutes(), d.getSeconds()]).toEqual([9, 30, 45]);
  });

  it.each(["", "abc", "2026-07-10", "2026-07-10 09:30", "2026-07-10T9:30", "2026-07-10T09:30Z"])("junk %j -> null", (s) => {
    expect(localDatetimeToIso(s)).toBeNull();
  });

  it("out-of-range fields roll over instead of failing", () => {
    // BUG: see PR — "2026-13-40T25:99" parses (Date overflow), not null
    // (latent: values come from <input type="datetime-local">, which never emits out-of-range fields).
    expect(toLocalDatetimeInput(new Date(localDatetimeToIso("2026-13-40T25:99")!))).toBe("2027-02-10T02:39");
  });
});

describe("predictNext", () => {
  it.each<[string, HistoryEntry[]]>([
    // [label, history]
    ["empty", []],
    ["only junk values", [entry("garbage-garbage-g", 0)]],
  ])("%s -> null", (_, h) => {
    expect(predictNext(h, at(10, 12))).toBeNull();
  });

  it.each<[string, HistoryEntry[], Date, Prediction]>([
    // [label, history, now, want]
    ["one pick 6h out -> +6h",
      [entry(v(10, 12), at(10, 6).getTime())], at(10, 7), { value: v(10, 18), intervalLabel: "6h", fromDelta: true }],
    ["one pick 30m out -> +30m",
      [entry(v(10, 12, 30), at(10, 12).getTime())], at(10, 12), { value: v(10, 13), intervalLabel: "30m", fromDelta: true }],
    ["one past-dated pick uses |gap|",
      [entry(v(10, 6), at(10, 12).getTime())], at(10, 5), { value: v(10, 12), intervalLabel: "6h", fromDelta: true }],
    ["one pick, prediction already past now -> rolls by the gap",
      [entry(v(10, 12), at(10, 6).getTime())], at(11, 1), { value: v(11, 6), intervalLabel: "6h", fromDelta: true }],
    ["one pick, gap < 5 min -> +1 day",
      [entry(v(10, 12), at(10, 11, 58).getTime())], at(10, 12), { value: v(11, 12), intervalLabel: "", fromDelta: false }],
    ["one pick, gap > 30 d -> +1 day, rolled past now",
      [entry(v(10, 12), at(10, 12).getTime() - 40 * 86400000)], at(12, 13), { value: v(13, 12), intervalLabel: "", fromDelta: false }],
    ["daily",
      [entry(v(10, 9)), entry(v(9, 9)), entry(v(8, 9))], at(10, 12), { value: v(11, 9), intervalLabel: "1d", fromDelta: true }],
    ["weekly",
      [entry(v(15, 18, 30)), entry(v(8, 18, 30)), entry(v(1, 18, 30))], at(16, 0), { value: v(22, 18, 30), intervalLabel: "7d", fromDelta: true }],
    ["weekly, prediction past -> rolls forward by weeks",
      [entry(v(15, 18, 30)), entry(v(8, 18, 30)), entry(v(1, 18, 30))], at(30, 0), { value: "2026-08-05T18:30", intervalLabel: "7d", fromDelta: true }],
    ["averages only the last 3 deltas",
      [entry(v(20, 9)), entry(v(19, 9)), entry(v(17, 9)), entry(v(16, 9)), entry(v(1, 9))], at(20, 10),
      { value: v(21, 17), intervalLabel: "1d 8h", fromDelta: true }],
    ["double-picks (< 5 min apart) -> +1 day",
      [entry(v(10, 9, 2)), entry(v(10, 9))], at(10, 8), { value: v(11, 9, 2), intervalLabel: "", fromDelta: false }],
    ["junk entries are skipped",
      [entry(v(10, 9)), entry("garbage-garbage-g"), entry(v(9, 9))], at(10, 8), { value: v(11, 9), intervalLabel: "1d", fromDelta: true }],
  ])("%s", (_, h, now, want) => {
    expect(predictNext(h, now)).toEqual(want);
  });

  it("one parsable pick behind a junk head reads the junk entry's savedAt", () => {
    // BUG: see PR — times[0] is history[1], but the gap uses history[0].savedAt (0 here) -> > 30 d -> +1 day
    // (latent: every recorded value comes from a datetime-local input, so a junk head never occurs).
    const h = [entry("garbage-garbage-g", 0), entry(v(10, 12), at(10, 6).getTime())];
    expect(predictNext(h, at(10, 7))).toEqual({ value: v(11, 12), intervalLabel: "", fromDelta: false });
  });
});

describe("describePrediction", () => {
  it("joins a host-locale date half and time half with ·", () => {
    const split = (s: string) => describePrediction(s).split(" · ");
    const [date, time, ...rest] = split(v(11, 21));
    expect(rest).toEqual([]);
    expect(date).toContain("11");
    const [nextDate, nextTime] = split(v(12, 21)); // next day: date differs, time same
    expect([nextDate !== date, nextTime]).toEqual([true, time]);
    const [morningDate, morningTime] = split(v(11, 9)); // 9:00: time differs, date same
    expect([morningDate, morningTime !== time]).toEqual([date, true]);
  });

  it.each(["", "soon", "2026-07-11"])("unparsable %j is returned as-is", (s) => {
    expect(describePrediction(s)).toBe(s);
  });
});
