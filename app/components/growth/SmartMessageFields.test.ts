/** SmartMessageFields' pure helpers: the stored payload read, the delay clamp, the draft, and the save round-trip. */
import { describe, expect, it } from "vitest";

import {
  MAX_PRICE_NOTE, clampDelay, collectExtras, extrasDraft, extrasOfPayload, type ExtrasDraft, type SmartExtras,
} from "./SmartMessageFields";

const NONE = { media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0 };
const START = "2026-07-01T09:00:00.000Z";
const END = "2026-08-01T09:00:00.000Z";
const FULL = {
  media_ids: [11, 12], price_cents: 1999, starts_at: START, ends_at: END, unsend_minutes: 125, delay_range: [5, 10],
};

describe("extrasOfPayload", () => {
  it.each([
    ["null", null],
    ["undefined", undefined],
    ["{}", {}],
  ])("%s -> all-off settings, no delay_range key", (_, p) => {
    const out = extrasOfPayload(p);
    expect(out).toEqual(NONE);
    expect("delay_range" in out).toBe(false);
  });

  it("full payload passes through", () => {
    expect(extrasOfPayload(FULL)).toEqual(FULL);
  });

  it.each([
    // [payload, want (merged over NONE)]
    [{ media_ids: "11,12" }, {}],
    [{ media_ids: [1, "2", 0, -3, 2.5, 4, null] }, { media_ids: [1, 4] }],
    [{ price_cents: 500 }, {}], // a price without media is dropped
    [{ media_ids: [1], price_cents: "500" }, { media_ids: [1] }],
    [{ media_ids: [1], price_cents: 12.5 }, { media_ids: [1] }],
    [{ media_ids: [1], price_cents: -100 }, { media_ids: [1] }],
    [{ starts_at: "nope", ends_at: 123 }, {}],
    [{ starts_at: START, ends_at: "" }, { starts_at: START }],
    [{ unsend_minutes: -5 }, {}],
    [{ unsend_minutes: "30" }, {}],
    [{ unsend_minutes: 1.5 }, {}],
  ])("untrusted fields fall back to off %j", (p, want) => {
    expect(extrasOfPayload(p as Record<string, unknown>)).toEqual({ ...NONE, ...want });
  });

  it.each([
    // [delay_range, want]
    [null, null],
    [undefined, null], // key present, value not a pair
    ["5-10", null],
    [[5], null],
    [[1, 2, 3], null],
    [[1.5, 3], null],
    [["1", "3"], null],
    [[10, 5], [5, 10]], // via clampDelay
  ])("delay_range %j -> %j", (r, want) => {
    expect(extrasOfPayload({ delay_range: r }).delay_range).toEqual(want);
  });

  it("does not read frequency", () => {
    expect("frequency" in extrasOfPayload({ frequency: "every" })).toBe(false);
  });
});

describe("clampDelay", () => {
  it.each([
    // [a, b, want]
    [5, 10, [5, 10]],
    [10, 5, [5, 10]], // swapped into order
    [100, 1, [1, 60]],
    [0, 0, [1, 2]], // equal pair widens by a minute
    [0, 1, [1, 2]],
    [30, 30, [30, 31]],
    [-5, 3, [1, 3]],
    [-5, -1, [1, 2]],
    [59, 60, [59, 60]],
    [60, 60, [59, 60]], // top end widens downward
    [61, 100, [59, 60]],
    // as coded: NaN is not clamped; both callers (extrasOfPayload, collectExtras) only pass integers.
    [Number.NaN, 5, [Number.NaN, 5]],
    [5, Number.NaN, [5, Number.NaN]],
  ])("(%s, %s) -> %j", (a, b, want) => {
    expect(clampDelay(a, b)).toEqual(want);
  });
});

describe("extrasDraft", () => {
  it("empty config -> defaults", () => {
    expect(extrasDraft({})).toEqual({
      media: [], price: "", frequency: "once",
      startsOn: false, startsAt: null, endsOn: false, endsAt: null,
      unsendOn: false, unsendH: "0", unsendM: "0",
      delayOn: false, delayA: "1", delayB: "3",
    });
  });

  it("delayDefault fills the off delay row", () => {
    const d = extrasDraft({ delay_range: null }, [5, 15]);
    expect([d.delayOn, d.delayA, d.delayB]).toEqual([false, "5", "15"]);
  });

  it("partial config (no Expiry)", () => {
    const d = extrasDraft(
      { media_ids: [7], price_cents: 1999, frequency: "every", starts_at: START, unsend_minutes: 125, delay_range: [2, 4] },
      [5, 15],
    );
    expect(d).toEqual({
      media: [{ id: 7, type: "photo" }], price: "19.99", frequency: "every",
      startsOn: true, startsAt: START, endsOn: false, endsAt: null,
      unsendOn: true, unsendH: "2", unsendM: "5",
      delayOn: true, delayA: "2", delayB: "4", // a stored range beats the default
    });
  });
});

describe("collectExtras round-trip", () => {
  it.each([
    // [name, payload, opts]
    ["full", FULL, { delay: true }],
    ["delay off", { ...FULL, delay_range: null }, { delay: true }],
    ["whole-dollar price", { ...FULL, price_cents: 300 }, { delay: true }],
    ["empty, no delay row", {}, {}],
  ])("editor-valid payloads round-trip: %s", (_, p, opts) => {
    const extras = extrasOfPayload(p);
    expect(collectExtras(extrasDraft(extras), opts)).toEqual(extras);
  });

  it.each([
    // [name, payload, want] — as coded: extrasOfPayload reads these, collectExtras refuses them
    ["price_cents 150 (< $3)", { media_ids: [1], price_cents: 150 }, "Minimum $3 USD"],
    ["unsend 1381 (> 23 h)", { unsend_minutes: 1381 }, "Unsend after 1 minute to 23 hours"],
  ])("read but refused on save: %s", (_, p, want) => {
    expect(collectExtras(extrasDraft(extrasOfPayload(p)))).toBe(want);
  });

  it("an untouched delay row is not sent", () => {
    const d = extrasDraft(extrasOfPayload(FULL));
    const { delay_range, ...rest } = extrasOfPayload(FULL);
    expect(delay_range).toEqual([5, 10]);
    expect(collectExtras(d, { delay: true, initial: d })).toEqual(rest);
  });
});

describe("collectExtras refusals", () => {
  const VALID = extrasDraft(extrasOfPayload(FULL));
  const SAVED = extrasOfPayload(FULL);
  const UNSEND = "Unsend after 1 minute to 23 hours";
  const DELAY = "The delay is whole minutes from 1 to 60";

  it.each<[string, Partial<ExtrasDraft>, string | Partial<SmartExtras>]>([
    // [name, draft patch over VALID, want]
    ["valid draft saves", {}, SAVED],
    ["price 2.50 (< $3)", { price: "2.50" }, "Minimum $3 USD"],
    ["price abc", { price: "abc" }, "Minimum $3 USD"],
    ["price 250", { price: "250" }, MAX_PRICE_NOTE],
    ["price 200.01", { price: "200.01" }, MAX_PRICE_NOTE],
    ["price 200", { price: "200" }, { ...SAVED, price_cents: 20000 }],
    ["price without media", { media: [] }, "Add media to set a price"],
    ["Effective on, no date", { startsAt: null }, "Pick the Effective date"],
    ["Expiry on, no date", { endsAt: null }, "Pick the Expiry date"],
    ["Expiry == Effective", { endsAt: START }, "The Expiry must come after the Effective date"],
    ["Expiry before Effective", { startsAt: END, endsAt: START }, "The Expiry must come after the Effective date"],
    ["unsend 23:01", { unsendH: "23", unsendM: "1" }, UNSEND],
    ["unsend 0:00", { unsendH: "0", unsendM: "0" }, UNSEND],
    ["unsend 24:00", { unsendH: "24", unsendM: "0" }, UNSEND],
    ["unsend x", { unsendH: "x" }, UNSEND],
    ["unsend 23:00", { unsendH: "23", unsendM: "0" }, { ...SAVED, unsend_minutes: 1380 }],
    ["delay 1.5", { delayA: "1.5" }, DELAY],
    ["delay empty", { delayB: "" }, DELAY],
  ])("%s", (_, patch, want) => {
    expect(collectExtras({ ...VALID, ...patch }, { delay: true })).toEqual(want);
  });

  it("opts.frequency sends the draft's frequency", () => {
    const d = { ...VALID, frequency: "every" as const };
    expect(collectExtras(d, { delay: true })).toEqual(SAVED);
    expect(collectExtras(d, { delay: true, frequency: true })).toEqual({ ...SAVED, frequency: "every" });
  });
});
