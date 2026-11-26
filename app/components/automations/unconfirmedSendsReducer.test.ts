import { describe, expect, it } from "vitest";

import {
  buildDismissPayload, buildRequest, buildRetryPayload, canAct, dismissQuestion, hintLine, initialOverlay, retryOutcome, rowKey, settleRows, unconfirmedSendsReducer as reduce,
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
    [200, "drop"], [404, "drop"], [409, "error"], [403, "error"], [500, "error"], [0, "error"],
  ] as const)("HTTP %i → %s (409 keeps the row: still sending, or the row changed since it was listed)", (status, out) => {
    expect(retryOutcome(status)).toBe(out);
  });
});

describe("rowKey / buildRetryPayload", () => {
  it("keys by kind, fan and mass run", () => {
    expect(rowKey(A)).toBe("funnel:1:7");
    expect(rowKey(B)).toBe("followup:2:");
  });
  it("sends mass_run_id only when set, and always the listed since", () => {
    expect(buildRetryPayload(A)).toEqual({ kind: "funnel", fan_id: "1", mass_run_id: 7, since: A.since });
    expect(buildRetryPayload(B)).toEqual({ kind: "followup", fan_id: "2", since: B.since });
  });
});

describe("viewRows", () => {
  it("no data → no rows", () => {
    expect(viewRows(undefined, initialOverlay)).toEqual([]);
  });
  it("UNCONFIRMED rows retryable, IN_FLIGHT not", () => {
    expect(viewRows(ROWS, initialOverlay).map((r) => [r.key, canAct(r)])).toEqual([
      ["funnel:1:7", true], ["followup:2:", true], ["funnel:3:7", false],
    ]);
  });
  it("the server state wins; the overlay keeps pending / error", () => {
    let o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "retry" });
    o = reduce(o, { type: "done", op: "retry", key: rowKey(B), result: { status: 500, message: "boom" } });
    const rows = [A, B, { ...C, state: "UNCONFIRMED" as const }];
    expect(find(o, A, rows)!.pending).toBe("retry");
    expect(find(o, B, rows)!.error).toBe("boom");
    expect(canAct(find(o, C, rows)!)).toBe(true);
  });
  it("rows the server no longer lists are gone", () => {
    const o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "retry" });
    expect(viewRows([B], o).map((r) => r.key)).toEqual([rowKey(B)]);
  });
});

describe("settleRows", () => {
  it.each([
    ["drop", [rowKey(B), rowKey(C)], undefined],
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
  ])("retry %s → overlay cleared (the rows: settleRows)", (_n, status, message) => {
    let o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "retry" });
    o = reduce(o, { type: "done", op: "retry", key: rowKey(A), result: { status, message } });
    expect(o).toEqual({});
  });

  it.each([
    [409, "this row changed since it was listed: refresh", "this row changed since it was listed: refresh"],
    [409, "still sending", "still sending"],
    [500, "boom", "boom"],
    [403, undefined, "Retry failed (HTTP 403)"],
    [0, "Failed to fetch", "Failed to fetch"],
  ])("retry error %i → row error, Retry re-enabled", (status, message, shown) => {
    let o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "retry" });
    o = reduce(o, { type: "done", op: "retry", key: rowKey(A), result: { status, message } });
    expect(find(o, A)).toMatchObject({ state: "UNCONFIRMED", pending: null, error: shown });
    expect(canAct(find(o, A)!)).toBe(true);
  });

  it("per-row pending: one row's Retry leaves the others retryable", () => {
    const o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "retry" });
    expect(find(o, A)!.pending).toBe("retry");
    expect(canAct(find(o, A)!)).toBe(false);
    expect(canAct(find(o, B)!)).toBe(true);
  });

  it("retryStart on a pending row is a no-op; a new Retry clears the old error", () => {
    const o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "retry" });
    expect(reduce(o, { type: "start", key: rowKey(A), op: "retry" })).toBe(o);
    let e = reduce(o, { type: "done", op: "retry", key: rowKey(A), result: { status: 500, message: "boom" } });
    e = reduce(e, { type: "start", key: rowKey(A), op: "retry" });
    expect(e[rowKey(A)]).toEqual({ pending: "retry", error: null });
  });

  it("retryDone drop on an unknown key is a no-op", () => {
    expect(reduce(initialOverlay, { type: "done", op: "retry", key: "funnel:9:7", result: { status: 200 } })).toBe(initialOverlay);
  });
});

describe("It went through (dismiss)", () => {
  const H = { ...A, hint: { message_id: "555", at: "2026-11-03T10:02:00Z", text: "hey you" } };

  it("body: Retry's + the hint the user saw", () => {
    expect(buildDismissPayload(A)).toEqual({ kind: "funnel", fan_id: "1", mass_run_id: 7, since: A.since });
    expect(buildDismissPayload(H)).toEqual({ kind: "funnel", fan_id: "1", mass_run_id: 7, since: H.since, hint_message_id: "555" });
    expect(buildDismissPayload({ ...B, hint: null })).toEqual({ kind: "followup", fan_id: "2", since: B.since });
  });

  it("the confirm says it is treated as sent and not sent again", () => {
    expect(dismissQuestion(A)).toMatch(/STEP 2 to fan 1 as sent/);
    expect(dismissQuestion(A)).toMatch(/treated as sent.*not sent again/);
  });

  it.each([
    [A, null],
    [H, "Sent to this fan at T(2026-11-03T10:02:00Z): hey you"],
    [{ ...A, hint: { ...H.hint, text: "x".repeat(60) } }, `Sent to this fan at T(2026-11-03T10:02:00Z): ${"x".repeat(60)}…`],
    [{ ...A, hint: { ...H.hint, text: "" } }, "Sent to this fan at T(2026-11-03T10:02:00Z): (no text)"],
  ])("hint line %#", (r, line) => {
    expect(hintLine(r, (iso) => `T(${iso})`)).toBe(line);
  });

  it("pending dismiss disables both ops on that row only; an error keeps the row with its text", () => {
    let o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "dismiss" });
    expect(find(o, A)!.pending).toBe("dismiss");
    expect(canAct(find(o, A)!)).toBe(false);
    expect(canAct(find(o, B)!)).toBe(true);
    expect(reduce(o, { type: "start", key: rowKey(A), op: "retry" })).toBe(o);
    o = reduce(o, { type: "done", op: "dismiss", key: rowKey(A), result: { status: 409, message: "still sending" } });
    expect(find(o, A)).toMatchObject({ state: "UNCONFIRMED", pending: null, error: "still sending" });
    expect(settleRows(ROWS, rowKey(A), retryOutcome(409))).toBe(ROWS);
    const e = reduce(reduce(initialOverlay, { type: "start", key: rowKey(A), op: "dismiss" }),
      { type: "done", op: "dismiss", key: rowKey(A), result: { status: 500 } });
    expect(e[rowKey(A)].error).toBe("Couldn't mark it as sent (HTTP 500)");
  });

  it("200 → overlay cleared, row dropped", () => {
    let o = reduce(initialOverlay, { type: "start", key: rowKey(A), op: "dismiss" });
    o = reduce(o, { type: "done", op: "dismiss", key: rowKey(A), result: { status: 200 } });
    expect(o).toEqual({});
    expect(settleRows(ROWS, rowKey(A), "drop")!.map(rowKey)).toEqual([rowKey(B), rowKey(C)]);
  });
});

describe("buildRequest", () => {
  const OP = { kind: "composer", op_id: "op-9", fan_id: "5", since: "x", state: "UNCONFIRMED", retry_allowed: false, link: "chat" } as const;
  it.each([
    ["marked retry (env unset)", A, "retry", "retry"],
    ["marked retry with retry_allowed:false", { ...A, retry_allowed: false }, "retry", null],
    ["marked dismiss with retry_allowed:false", { ...A, retry_allowed: false }, "dismiss", "dismiss"],
    ["marked row resolve", A, "was_sent", null],
    ["op was_sent", OP, "was_sent", "resolve"],
    ["op not_sent", OP, "not_sent", "resolve"],
    ["op retry", OP, "retry", null],
    ["op dismiss", OP, "dismiss", null],
  ] as const)("%s → %s", (_n, r, op, path) => {
    expect(buildRequest(r, op)?.path ?? null).toBe(path);
  });
  it("op body is op_id + outcome; marked retry has no confirm, dismiss does", () => {
    expect(buildRequest(OP, "not_sent")?.body).toEqual({ op_id: "op-9", outcome: "not_sent" });
    expect(buildRequest(A, "retry")?.confirm).toBeNull();
    expect(buildRequest(A, "dismiss")?.confirm?.label).toBe("It went through");
    expect(rowKey(OP)).toBe("op:op-9");
  });
});
