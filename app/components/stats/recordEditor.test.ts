import { describe, expect, it } from "vitest";

import {
  initialRecordForm, recordFormReducer, validateRecord, type RecordForm, type RecordFormAction,
} from "@/components/stats/recordEditor";

/** Wall clock in New York (EDT, UTC-4 in October). */
const TZ = "America/New_York";
const CLOSED = { in_utc: "2026-10-14T13:00:00Z", out_utc: "2026-10-14T15:05:30Z" };
const OPEN = { in_utc: "2026-10-15T12:00:00Z", out_utc: null };

describe("initialRecordForm", () => {
  it.each([
    ["closed record", CLOSED, false, { inV: "2026-10-14T09:00", outV: "2026-10-14T11:05" }],
    ["open record", OPEN, false, { inV: "2026-10-15T08:00", outV: "" }],
    ["closing opens on now", OPEN, true, { inV: "2026-10-15T08:00", outV: "2026-10-15T10:07" }],
  ])("%s", (_, r, closing, want) => {
    expect(initialRecordForm(r, TZ, closing, new Date("2026-10-15T14:07:42Z")))
      .toEqual({ ...want, busy: false, error: null });
  });
});

describe("recordFormReducer", () => {
  const S: RecordForm = { inV: "a", outV: "b", busy: false, error: "old" };
  it.each<[string, RecordForm, RecordFormAction, Partial<RecordForm>]>([
    ["in edits the clock in only", S, { type: "in", value: "x" }, { inV: "x" }],
    ["out edits the clock out only", S, { type: "out", value: "y" }, { outV: "y" }],
    ["saving clears the error, sets busy", S, { type: "saving" }, { busy: true, error: null }],
    ["error ends busy, shows the text", { ...S, busy: true }, { type: "error", error: "409" }, { busy: false, error: "409" }],
  ])("%s", (_, state, action, change) => {
    expect(recordFormReducer(state, action)).toEqual({ ...state, ...change });
  });
});

describe("validateRecord", () => {
  it.each<[string, typeof CLOSED | typeof OPEN, { inV: string; outV: string }, boolean, unknown]>([
    ["nothing changed → unchanged", CLOSED, { inV: "2026-10-14T09:00", outV: "2026-10-14T11:05" }, false, { kind: "unchanged" }],
    ["clock in moved → in_utc only", CLOSED, { inV: "2026-10-14T08:30", outV: "2026-10-14T11:05" }, false,
      { kind: "send", body: { in_utc: "2026-10-14T12:30:00.000Z" } }],
    ["clock out moved → out_utc only", CLOSED, { inV: "2026-10-14T09:00", outV: "2026-10-14T12:00" }, false,
      { kind: "send", body: { out_utc: "2026-10-14T16:00:00.000Z" } }],
    ["both moved → both", CLOSED, { inV: "2026-10-14T07:00", outV: "2026-10-14T08:00" }, false,
      { kind: "send", body: { in_utc: "2026-10-14T11:00:00.000Z", out_utc: "2026-10-14T12:00:00.000Z" } }],
    ["closing sends out_utc even unchanged-looking, never in", OPEN, { inV: "2026-10-15T07:00", outV: "2026-10-15T10:07" }, true,
      { kind: "send", body: { out_utc: "2026-10-15T14:07:00.000Z" } }],
    ["open record, clock in moved → in_utc only", OPEN, { inV: "2026-10-15T07:00", outV: "" }, false,
      { kind: "send", body: { in_utc: "2026-10-15T11:00:00.000Z" } }],
    ["empty clock in", CLOSED, { inV: "", outV: "2026-10-14T11:05" }, false, { kind: "error", error: "Enter a clock in time." }],
    ["empty clock out", CLOSED, { inV: "2026-10-14T09:00", outV: "" }, false, { kind: "error", error: "Enter a clock out time." }],
    ["closing with empty clock out", OPEN, { inV: "2026-10-15T08:00", outV: "" }, true, { kind: "error", error: "Enter a clock out time." }],
    ["new clock out before kept clock in", CLOSED, { inV: "2026-10-14T09:00", outV: "2026-10-14T08:00" }, false,
      { kind: "error", error: "Clock out must be after clock in." }],
    ["new clock out equal to kept clock in", CLOSED, { inV: "2026-10-14T09:00", outV: "2026-10-14T09:00" }, false,
      { kind: "error", error: "Clock out must be after clock in." }],
    ["new clock in after kept clock out", CLOSED, { inV: "2026-10-14T12:00", outV: "2026-10-14T11:05" }, false,
      { kind: "error", error: "Clock out must be after clock in." }],
    ["both moved, inverted", CLOSED, { inV: "2026-10-14T10:00", outV: "2026-10-14T09:30" }, false,
      { kind: "error", error: "Clock out must be after clock in." }],
    ["closing before the clock in", OPEN, { inV: "2026-10-15T08:00", outV: "2026-10-15T07:59" }, true,
      { kind: "error", error: "Clock out must be after clock in." }],
    ["open record: any clock in passes (no clock out to compare)", OPEN, { inV: "2026-10-16T08:00", outV: "" }, false,
      { kind: "send", body: { in_utc: "2026-10-16T12:00:00.000Z" } }],
  ])("%s", (_, r, form, closing, want) => {
    expect(validateRecord(r, form, TZ, closing)).toEqual(want);
  });
});
