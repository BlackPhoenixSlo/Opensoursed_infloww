import { describe, expect, it } from "vitest";

import {
  buildRetryPayload, canRetry, initialOverlay, retryOutcome, rowKey, settleRows, unconfirmedSendsReducer as reduce,
  viewRows, type Overlay, type UnconfirmedRow,
} from "@/components/automations/unconfirmedSendsReducer";

function row(fan: string, over: Partial<UnconfirmedRow> = {}): UnconfirmedRow {
  return {
    kind: "funnel", fan_id: fan, mass_run_id: 7, step: 2, step_label: "STEP 2",
    since: "2026-11-03T10:00:00", last_error: "may not have sent: ReadTimeout", state: "UNCONFIRMED", ...over,
  };
}
const A = row("1");
const B = row("2", { kind: "followup", mass_run_id: null, step_label: "STEP 1" });
const C = row("3", { state: "IN_FLIGHT" });
const ROWS = [A, B, C];
const find = (o: Overlay, r: UnconfirmedRow, rows = ROWS) => viewRows(rows, o).find((v) => v.key === rowKey(r));

describe("retryOutcome", () => {
  it.each([
    [200, "drop"], [404, "drop"], [409, "sending"], [403, "error"], [500, "error"], [0, "error"],
  ] as const)("HTTP %i → %s", (status, out) => {
    expect(retryOutcome(status)).toBe(out);
  });
});

describe("rowKey / buildRetryPayload", () => {
  it("keys by kind, fan and mass run", () => {
    expect(rowKey(A)).toBe("funnel:1:7");
    expect(rowKey(B)).toBe("followup:2:");
  });
  it("sends mass_run_id only when set", () => {
    expect(buildRetryPayload(A)).toEqual({ kind: "funnel", fan_id: "1", mass_run_id: 7 });
    expect(buildRetryPayload(B)).toEqual({ kind: "followup", fan_id: "2" });
  });
});

describe("viewRows", () => {
  it("no data → no rows", () => {
    expect(viewRows(undefined, initialOverlay)).toEqual([]);
  });
  it("UNCONFIRMED rows retryable, IN_FLIGHT not", () => {
    expect(viewRows(ROWS, initialOverlay).map((r) => [r.key, canRetry(r)])).toEqual([
      ["funnel:1:7", true], ["followup:2:", true], ["funnel:3:7", false],
    ]);
  });
  it("the server state wins; the overlay keeps pending / error", () => {
    let o = reduce(initialOverlay, { type: "retryStart", key: rowKey(A) });
    o = reduce(o, { type: "retryDone", key: rowKey(B), result: { status: 500, message: "boom" } });
    const rows = [A, B, { ...C, state: "UNCONFIRMED" as const }];
    expect(find(o, A, rows)!.pending).toBe(true);
    expect(find(o, B, rows)!.error).toBe("boom");
    expect(canRetry(find(o, C, rows)!)).toBe(true);
  });
  it("rows the server no longer lists are gone", () => {
    const o = reduce(initialOverlay, { type: "retryStart", key: rowKey(A) });
    expect(viewRows([B], o).map((r) => r.key)).toEqual([rowKey(B)]);
  });
});

describe("settleRows", () => {
  it.each([
    ["drop", [rowKey(B), rowKey(C)], undefined],
    ["sending", [rowKey(A), rowKey(B), rowKey(C)], "IN_FLIGHT"],
    ["error", [rowKey(A), rowKey(B), rowKey(C)], "UNCONFIRMED"],
  ] as const)("%s → A as expected, others untouched", (out, keys, stateA) => {
    const got = settleRows(ROWS, rowKey(A), out)!;
    expect(got.map(rowKey)).toEqual(keys);
    expect(got.find((r) => rowKey(r) === rowKey(A))?.state).toBe(stateA);
    expect(got.filter((r) => rowKey(r) !== rowKey(A))).toEqual([B, C]);
  });
  it("no cached rows → none", () => {
    expect(settleRows(undefined, rowKey(A), "drop")).toBeUndefined();
  });
});

describe("unconfirmedSendsReducer (the overlay)", () => {
  it.each([
    ["200 (retried / already_sent)", 200, undefined],
    ["404 gone", 404, "not found"],
    ["409 in flight", 409, "in flight"],
  ])("retry %s → overlay cleared (the rows: settleRows)", (_n, status, message) => {
    let o = reduce(initialOverlay, { type: "retryStart", key: rowKey(A) });
    o = reduce(o, { type: "retryDone", key: rowKey(A), result: { status, message } });
    expect(o).toEqual({});
  });

  it("409 → Sending, no Retry", () => {
    let o = reduce(initialOverlay, { type: "retryStart", key: rowKey(A) });
    o = reduce(o, { type: "retryDone", key: rowKey(A), result: { status: 409, message: "in flight" } });
    const v = find(o, A, settleRows(ROWS, rowKey(A), "sending"));
    expect(v).toMatchObject({ state: "IN_FLIGHT", pending: false, error: null });
    expect(canRetry(v!)).toBe(false);
  });

  it.each([
    [500, "boom", "boom"],
    [403, undefined, "Retry failed (HTTP 403)"],
    [0, "Failed to fetch", "Failed to fetch"],
  ])("retry error %i → row error, Retry re-enabled", (status, message, shown) => {
    let o = reduce(initialOverlay, { type: "retryStart", key: rowKey(A) });
    o = reduce(o, { type: "retryDone", key: rowKey(A), result: { status, message } });
    expect(find(o, A)).toMatchObject({ state: "UNCONFIRMED", pending: false, error: shown });
    expect(canRetry(find(o, A)!)).toBe(true);
  });

  it("per-row pending: one row's Retry leaves the others retryable", () => {
    const o = reduce(initialOverlay, { type: "retryStart", key: rowKey(A) });
    expect(find(o, A)!.pending).toBe(true);
    expect(canRetry(find(o, A)!)).toBe(false);
    expect(canRetry(find(o, B)!)).toBe(true);
  });

  it("retryStart on a pending row is a no-op; a new Retry clears the old error", () => {
    const o = reduce(initialOverlay, { type: "retryStart", key: rowKey(A) });
    expect(reduce(o, { type: "retryStart", key: rowKey(A) })).toBe(o);
    let e = reduce(o, { type: "retryDone", key: rowKey(A), result: { status: 500, message: "boom" } });
    e = reduce(e, { type: "retryStart", key: rowKey(A) });
    expect(e[rowKey(A)]).toEqual({ pending: true, error: null });
  });

  it("retryDone drop on an unknown key is a no-op", () => {
    expect(reduce(initialOverlay, { type: "retryDone", key: "funnel:9:7", result: { status: 200 } })).toBe(initialOverlay);
  });
});
