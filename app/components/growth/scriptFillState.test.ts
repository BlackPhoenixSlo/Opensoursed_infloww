import { describe, expect, it } from "vitest";

import {
  ASK_OWNER, INITIAL_FILL, canDescribe, conflictLines, dialogFor, fillKey, fillRefusalText, isLocked, leftNote,
  leftText, noticeCounts, noticeText, scriptFillReducer, undoPayload, type Action, type ScriptFillState,
  type SweepView,
} from "@/components/growth/scriptFillState";
import { stalePlan } from "@/hooks/useSavedReplies";
import { GENERIC_REFUSAL, WHOLE_VAULT, refusalText } from "@/hooks/useVaultSweep";
import {
  ApiKeyError, RelayError, type FillConflictRule, type FillKeptReason, type FillOption, type FillPlan, type FillStatus,
} from "@/lib/relay";

const A = "acc-a";
const B = "acc-b";
const SEQ = "New Sub";
const OTHER = "Old Sub";
const K = fillKey(A, SEQ);

const opt = (over: Partial<FillOption>): FillOption => ({
  id: 1, step: 1, option: 1, role: "paid_media", wants: "photo", keep: false, media: [], previews: [],
  price_cents: 0, price_fixed: false, flags: [], ...over,
});

const plan = (status: FillStatus, over: Partial<FillPlan> = {}): FillPlan => ({
  status, options: [], flags: [], conflict: null,
  describe: { described: 120, target: 1000, remaining: 880, can_describe: true, blocked_reason: null },
  fingerprint: "fp", ...over,
});

const run = (actions: Action[], from: ScriptFillState = INITIAL_FILL) => actions.reduce(scriptFillReducer, from);
const on = (account = A, open: string | null = SEQ): Action[] => [
  { type: "reset", account }, { type: "show", sequence: open },
];

const APPLIED = {
  applied: [
    opt({ id: 11, step: 2, media: [701, 702], previews: [701] }),
    opt({ id: 12, step: 2, option: 2, media: [701, 702], previews: [701] }),
    opt({ id: 13, step: 3, media: [703] }),
  ],
  undo: [
    { id: 11, media_ids: [701, 702], previews: [701], price_cents: 1500, price_set: true },
    { id: 13, media_ids: [703], previews: [], price_cents: 2000, price_set: false },
  ],
};

describe("scriptFillReducer", () => {
  it("press → applied records the notice with apply's Undo list and the counts, under (Creator, Sequence)", () => {
    const s = run([...on(), { type: "press", account: A, sequence: SEQ, req: 1 },
      { type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED }]);
    expect(s.inflight).toEqual({});
    expect(s.notices).toEqual({ [K]: { account: A, sequence: SEQ, undo: APPLIED.undo, n: 3, m: 2 } });
    expect(s.dialog).toBeNull();
  });

  it("press records its request under (Creator, Sequence); the page holds the one in-flight guard", () => {
    const s = run([...on(), { type: "press", account: A, sequence: SEQ, req: 1 }]);
    expect(s.inflight).toEqual({ [K]: 1 });
  });

  it.each<[string, FillStatus]>([["not_enough_content", "not_enough_content"], ["no_fit", "no_fit"], ["reserved", "reserved"]])(
    "a non-ok answer (%s) opens the dialog on it", (_n, status) => {
      const s = run([...on(), { type: "press", account: A, sequence: SEQ, req: 1 },
        { type: "answered", account: A, sequence: SEQ, req: 1, status }]);
      expect(s.dialog).toEqual({ sequence: SEQ, req: 1, status, refusal: null });
      expect(s.inflight).toEqual({});
    });

  it("an HTTP error opens the dialog on its sentence", () => {
    const s = run([...on(), { type: "press", account: A, sequence: SEQ, req: 1 },
      { type: "failed", account: A, sequence: SEQ, req: 1, message: "Could not reach the relay." }]);
    expect(s.dialog).toEqual({ sequence: SEQ, req: 1, status: null, refusal: "Could not reach the relay." });
  });

  const locked = (s: ScriptFillState, account: string | null, seq: string) => isLocked(s, account, seq, false);
  it.each<[string, Action[], boolean]>([
    ["press locks its Sequence", [{ type: "press", account: A, sequence: SEQ, req: 1 }], true],
    ["undoPress locks it too", [{ type: "undoPress", account: A, sequence: SEQ, req: 1 }], true],
    ["applied unlocks", [{ type: "press", account: A, sequence: SEQ, req: 1 },
      { type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED }], false],
    ["answered unlocks", [{ type: "press", account: A, sequence: SEQ, req: 1 },
      { type: "answered", account: A, sequence: SEQ, req: 1, status: "no_fit" }], false],
    ["failed unlocks", [{ type: "press", account: A, sequence: SEQ, req: 1 },
      { type: "failed", account: A, sequence: SEQ, req: 1, message: "x" }], false],
    ["undone unlocks", [{ type: "undoPress", account: A, sequence: SEQ, req: 1 },
      { type: "undone", account: A, sequence: SEQ, req: 1, result: { undone: [], kept: [] } }], false],
    ["another request's answer keeps the lock", [{ type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "failed", account: A, sequence: SEQ, req: 1, message: "x" }], true],
    ["a failed answer on another Creator's Sequence unlocks it while another Creator shows",
      [{ type: "press", account: A, sequence: SEQ, req: 1 }, { type: "reset", account: B },
        { type: "failed", account: A, sequence: SEQ, req: 1, message: "x" }], false],
  ])("lock: %s", (_n, actions, want) => {
    expect(locked(run([...on(), ...actions]), A, SEQ)).toBe(want);
  });

  it.each<[string, Action[]]>([
    ["no request", []],
    ["after an answer", [{ type: "press", account: A, sequence: SEQ, req: 1 },
      { type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED }]],
    ["after an Undo's answer", [{ type: "undoPress", account: A, sequence: SEQ, req: 1 },
      { type: "undone", account: A, sequence: SEQ, req: 1, result: { undone: [], kept: [] } }]],
  ])("a failed list locks every Sequence: %s", (_n, actions) => {
    expect(isLocked(run([...on(), ...actions]), A, SEQ, true)).toBe(true);
  });

  it("a lock is per Creator and Sequence", () => {
    const s = run([...on(), { type: "press", account: A, sequence: SEQ, req: 1 }]);
    expect(locked(s, A, OTHER)).toBe(false);
    expect(locked(s, B, SEQ)).toBe(false);
  });

  const pressed = run([...on(), { type: "press", account: A, sequence: SEQ, req: 1 }]);
  it.each<[string, Action]>([
    ["answered for another Creator", { type: "answered", account: B, sequence: SEQ, req: 1, status: "no_fit" }],
    ["answered for another request", { type: "answered", account: A, sequence: SEQ, req: 9, status: "no_fit" }],
    ["answered for another Sequence", { type: "answered", account: A, sequence: OTHER, req: 1, status: "no_fit" }],
    ["failed for another Creator", { type: "failed", account: B, sequence: SEQ, req: 1, message: "x" }],
    ["failed for another request", { type: "failed", account: A, sequence: SEQ, req: 9, message: "x" }],
    ["applied for another Creator's Sequence not in flight", { type: "applied", account: B, sequence: SEQ, req: 1, result: APPLIED }],
    ["applied for another request", { type: "applied", account: A, sequence: SEQ, req: 9, result: APPLIED }],
    ["undone for another Creator", { type: "undone", account: B, sequence: SEQ, req: 1, result: { undone: [], kept: [] } }],
    ["undone for another request", { type: "undone", account: A, sequence: SEQ, req: 9, result: { undone: [], kept: [] } }],
  ])("drops a late %s", (_n, late) => {
    const s = run([late], pressed);
    expect(s.dialog).toBeNull();
    expect(s.notices).toEqual({});
    expect(s.inflight).toEqual({ [K]: 1 });
  });

  it("an ok after switching Sequence keeps its notice (and Undo) for that Sequence, without a dialog", () => {
    const moved = run([{ type: "show", sequence: OTHER }], pressed);
    const ok = run([{ type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED }], moved);
    expect(ok.inflight).toEqual({});
    expect(ok.notices).toEqual({ [K]: { account: A, sequence: SEQ, undo: APPLIED.undo, n: 3, m: 2 } });
    expect(ok.dialog).toBeNull();
    expect(run([{ type: "show", sequence: SEQ }], ok).notices[K]?.undo).toBe(APPLIED.undo);
  });

  it("a non-ok answer after switching Sequence ends its request but opens no dialog", () => {
    const moved = run([{ type: "show", sequence: OTHER }], pressed);
    for (const late of [
      { type: "answered", account: A, sequence: SEQ, req: 1, status: "no_fit" },
      { type: "failed", account: A, sequence: SEQ, req: 1, message: "x" },
    ] as Action[]) {
      const s = run([late], moved);
      expect(s.dialog).toBeNull();
      expect(s.notices).toEqual({});
      expect(s.inflight).toEqual({});
    }
  });

  const SECOND = {
    applied: [opt({ id: 14, step: 4, media: [704, 705] })],
    undo: [{ id: 14, media_ids: [704, 705], previews: [], price_cents: 900, price_set: true }],
  };
  const filled = run([{ type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED }], pressed);
  it.each<[string, Action[], { undo: unknown[]; n: number; m: number }]>([
    ["a second ok appends its Undo list and adds up n and m", [
      { type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "applied", account: A, sequence: SEQ, req: 2, result: SECOND },
    ], { undo: [...APPLIED.undo, ...SECOND.undo], n: 5, m: 3 }],
    ["a zero-write ok keeps the notice as it was", [
      { type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "applied", account: A, sequence: SEQ, req: 2, result: { applied: [], undo: [] } },
    ], { undo: APPLIED.undo, n: 3, m: 2 }],
    ["already_filled keeps the notice", [
      { type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "answered", account: A, sequence: SEQ, req: 2, status: "already_filled" },
    ], { undo: APPLIED.undo, n: 3, m: 2 }],
    ["a failed second press keeps the notice", [
      { type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "failed", account: A, sequence: SEQ, req: 2, message: "x" },
    ], { undo: APPLIED.undo, n: 3, m: 2 }],
    ["describing more, then a second ok: both writes' Undo", [
      { type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "answered", account: A, sequence: SEQ, req: 2, status: "not_enough_content" },
      { type: "press", account: A, sequence: SEQ, req: 3 },
      { type: "applied", account: A, sequence: SEQ, req: 3, result: SECOND },
    ], { undo: [...APPLIED.undo, ...SECOND.undo], n: 5, m: 3 }],
  ])("%s", (_n, actions, want) => {
    const s = run(actions, filled);
    expect(s.notices).toEqual({ [K]: { account: A, sequence: SEQ, ...want } });
    expect(s.inflight).toEqual({});
  });

  it("an ok answered after switching Creator is kept under its own (Creator, Sequence) and shown on return", () => {
    const away = run([{ type: "reset", account: B }], pressed);
    const ok = run([{ type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED }], away);
    expect(ok.inflight).toEqual({});
    expect(ok.dialog).toBeNull();
    expect(ok.notices[fillKey(B, SEQ)]).toBeUndefined();
    expect(ok.notices[K]).toEqual({ account: A, sequence: SEQ, undo: APPLIED.undo, n: 3, m: 2 });
    const back = run([{ type: "reset", account: A }, { type: "show", sequence: SEQ }], ok);
    const notice = back.notices[K]!;
    expect(notice.account).toBe(A);
    expect(undoPayload(notice)).toEqual({ sequence: SEQ, undo: APPLIED.undo });
    const undone = run([{ type: "undoPress", account: notice.account, sequence: SEQ, req: 2 },
      { type: "undone", account: A, sequence: SEQ, req: 2, result: { undone: [11, 13], kept: [] } }], back);
    expect(undone.notices).toEqual({});
  });

  it("a non-ok answer after switching Creator ends its request but opens no dialog", () => {
    const away = run([{ type: "reset", account: B }], pressed);
    for (const late of [
      { type: "answered", account: A, sequence: SEQ, req: 1, status: "no_fit" },
      { type: "failed", account: A, sequence: SEQ, req: 1, message: "x" },
    ] as Action[]) {
      const s = run([late], away);
      expect(s.dialog).toBeNull();
      expect(s.inflight).toEqual({});
    }
  });

  it("an Undo answered after switching Creator clears that Creator's notice and keeps its left note there", () => {
    const undoing = run([{ type: "undoPress", account: A, sequence: SEQ, req: 2 }, { type: "reset", account: B }], filled);
    const s = run([{ type: "undone", account: A, sequence: SEQ, req: 2,
      result: { undone: [11], kept: [{ id: 13, reason: "edited" }] } }], undoing);
    expect(s.notices).toEqual({});
    expect(s.left).toEqual({ [K]: { changed: 1, moved: 0, reserved: 0, other: 0 } });
  });

  it("opening another Sequence closes the dialog; showing the same one keeps it", () => {
    const open = run([{ type: "answered", account: A, sequence: SEQ, req: 1, status: "no_fit" }], pressed);
    expect(run([{ type: "show", sequence: SEQ }], open).dialog?.status).toBe("no_fit");
    expect(run([{ type: "show", sequence: OTHER }], open).dialog).toBeNull();
    expect(run([{ type: "show", sequence: null }], open).dialog).toBeNull();
  });

  it("a notice survives switching Sequence and back", () => {
    const s = run([...on(), { type: "press", account: A, sequence: SEQ, req: 1 },
      { type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED },
      { type: "show", sequence: OTHER }, { type: "show", sequence: SEQ }]);
    expect(s.notices[K]?.n).toBe(3);
  });

  it("describeRefused lands on the dialog of its own request only", () => {
    const open = run([{ type: "answered", account: A, sequence: SEQ, req: 1, status: "not_enough_content" }], pressed);
    expect(run([{ type: "describeRefused", account: A, sequence: SEQ, req: 1, message: "cap" }], open).dialog?.refusal)
      .toBe("cap");
    for (const late of [
      { type: "describeRefused", account: B, sequence: SEQ, req: 1, message: "cap" },
      { type: "describeRefused", account: A, sequence: OTHER, req: 1, message: "cap" },
      { type: "describeRefused", account: A, sequence: SEQ, req: 2, message: "cap" },
    ] as Action[]) expect(run([late], open).dialog?.refusal).toBeNull();
    const closed = run([{ type: "close" }], open);
    expect(run([{ type: "describeRefused", account: A, sequence: SEQ, req: 1, message: "cap" }], closed).dialog).toBeNull();
  });

  it("an ok from the dialog's Ready press closes the dialog and records the notice", () => {
    const open = run([{ type: "answered", account: A, sequence: SEQ, req: 1, status: "not_enough_content" },
      { type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "applied", account: A, sequence: SEQ, req: 2, result: APPLIED }], pressed);
    expect(open.dialog).toBeNull();
    expect(open.notices[K]).toBeTruthy();
  });

  it("undone clears the notice and keeps a left note when rows were left; dismiss drops both", () => {
    const left = run([{ type: "undoPress", account: A, sequence: SEQ, req: 2 },
      { type: "undone", account: A, sequence: SEQ, req: 2, result: { undone: [11], kept: [{ id: 13, reason: "edited" }] } }],
    filled);
    expect(left.notices).toEqual({});
    expect(left.left[K]).toEqual({ changed: 1, moved: 0, reserved: 0, other: 0 });
    expect(run([{ type: "dismiss", account: A, sequence: SEQ }], left).left).toEqual({});
    const clean = run([{ type: "undoPress", account: A, sequence: SEQ, req: 2 },
      { type: "undone", account: A, sequence: SEQ, req: 2, result: { undone: [11, 13], kept: [] } }], filled);
    expect(clean.left).toEqual({});
    expect(run([{ type: "dismiss", account: A, sequence: SEQ }], filled).notices).toEqual({});
    expect(run([{ type: "dismiss", account: B, sequence: SEQ }], filled).notices[K]).toBeTruthy();
  });

  it("reset closes the dialog and keeps the open Sequence, notices, left notes and requests in flight", () => {
    const open = run([{ type: "applied", account: A, sequence: SEQ, req: 1, result: APPLIED },
      { type: "press", account: A, sequence: SEQ, req: 2 },
      { type: "answered", account: A, sequence: SEQ, req: 2, status: "no_fit" },
      { type: "press", account: A, sequence: SEQ, req: 3 }], pressed);
    expect(open.dialog).not.toBeNull();
    const s = run([{ type: "reset", account: B }], open);
    expect(s).toEqual({ ...open, account: B, dialog: null });
  });
});

describe("noticeCounts / noticeText / undoPayload / leftNote", () => {
  it("counts distinct media ids (previews included) and distinct Steps", () => {
    expect(noticeCounts(APPLIED.applied)).toEqual({ n: 3, m: 2 });
    expect(noticeCounts([opt({ step: 1, media: [5, 6], previews: [5] }), opt({ step: 4, media: [], previews: [9] })]))
      .toEqual({ n: 3, m: 2 });
  });

  it.each<[number, number, string]>([
    [3, 2, "Added 3 items to 2 steps"],
    [1, 1, "Added 1 item to 1 step"],
    [1, 2, "Added 1 item to 2 steps"],
    [2, 1, "Added 2 items to 1 step"],
  ])("noticeText(%i, %i)", (n, m, text) => expect(noticeText({ n, m })).toBe(text));

  it("passes each entry's price_cents and price_set verbatim", () => {
    const body = undoPayload({ account: A, sequence: SEQ, undo: APPLIED.undo, n: 3, m: 2 });
    expect(body).toEqual({ sequence: SEQ, undo: APPLIED.undo });
    expect(body.undo[1]).toEqual({ id: 13, media_ids: [703], previews: [], price_cents: 2000, price_set: false });
  });

  const z = { changed: 0, moved: 0, reserved: 0, other: 0 };
  it.each<[string, string[], typeof z, string]>([
    ["edited", ["edited"], { ...z, changed: 1 }, "Undo left 1 step: 1 changed since the Fill."],
    ["moved", ["moved"], { ...z, moved: 1 }, "Undo left 1 step: 1 moved or deleted."],
    ["missing", ["missing", "missing"], { ...z, moved: 2 }, "Undo left 2 steps: 2 moved or deleted."],
    ["mixed", ["edited", "moved", "missing"], { ...z, changed: 1, moved: 2 },
      "Undo left 3 steps: 1 changed since the Fill, 2 moved or deleted."],
    ["reserved", ["reserved", "reserved"], { ...z, reserved: 2 },
      "Undo left 2 steps: 2 in a sequence generated by a script source."],
    ["an unknown reason", ["locked"], { ...z, other: 1 }, "Undo left 1 step: 1 could not be undone."],
  ])("leftNote: %s", (_n, reasons, counts, text) => {
    const c = leftNote({ undone: [], kept: reasons.map((reason, i) => ({ id: i, reason: reason as FillKeptReason })) });
    expect(c).toEqual(counts);
    expect(leftText(c)).toBe(text);
  });
});

describe("conflictLines", () => {
  const FIX = " — fix the price, then fill again.";
  it.each<[string, FillPlan["conflict"], FillOption[], string]>([
    ["Fixed descend names the nearest earlier Step priced higher", { step: 3, rule: "below_earlier", price_cents: 1000 }, [
      opt({ id: 1, step: 1, price_cents: 1500, price_fixed: true }),
      opt({ id: 2, step: 2, price_cents: 2000, price_fixed: true }),
      opt({ id: 3, step: 3, price_cents: 1000, price_fixed: true }),
    ], "Step 3 is priced below step 2"],
    ["an unpriced Step under an earlier floor above a later Fixed ceiling", { step: 2, rule: "below_earlier", price_cents: 1200 }, [
      opt({ id: 1, step: 1, price_cents: 3000, price_fixed: true }),
      opt({ id: 2, step: 2 }),
      opt({ id: 3, step: 3, price_cents: 2000, price_fixed: true }),
    ], "Step 1 is priced above step 3"],
    ["under $3", { step: 4, rule: "under_min", price_cents: 200 }, [], "Step 4: $2 is under OnlyFans' $3 minimum"],
    ["over $200", { step: 2, rule: "over_max", price_cents: 25050 }, [], "Step 2: $250.50 is over the $200 cap"],
    ["a quoted price below an earlier Fixed one", { step: 3, rule: "quote_unholdable", price_cents: 500 }, [
      opt({ id: 1, step: 2, price_cents: 900, price_fixed: true }),
    ], "Step 3: $5 is priced below step 2"],
    ["a rule this build doesn't know", { step: 4, rule: "new_rule" as FillConflictRule, price_cents: 200 }, [
      opt({ id: 1, step: 2, price_cents: 900, price_fixed: true }),
    ], "Step 4: $2 breaks a price rule"],
  ])("%s", (_n, conflict, options, line) => {
    expect(conflictLines(conflict, options)).toEqual([line + FIX]);
  });

  it("no conflict, no lines", () => expect(conflictLines(null, [])).toEqual([]));
});

describe("refusalText / fillRefusalText / stalePlan", () => {
  const KEY = {
    error: "api_key_missing" as const, feature: "describe_media", provider: "typesafe", fix_url: "/settings",
    message: "No vision key is set.", fix: "Paste one in Settings › AI keys.",
  };
  const CAP = "Today's AI budget for this account is spent — $1.00. It resets at 00:00 UTC.";
  it.each<[string, unknown, string]>([
    ["424 key payload", new ApiKeyError(424, { detail: KEY }, KEY), "No vision key is set. Paste one in Settings › AI keys."],
    ["429 with blocked_reason", new RelayError(429, { detail: { error: "daily_cap_reached", blocked_reason: CAP } },
      '{"error":"daily_cap_reached"}'), CAP],
    ["403 folder_not_allowed (generic)", new RelayError(403, { detail: { error: "folder_not_allowed" } },
      '{"error":"folder_not_allowed"}'), WHOLE_VAULT],
    ["403 role string", new RelayError(403, { detail: "Your role does not allow Vault Pro" }, "Your role does not allow Vault Pro"),
      "Your role does not allow Vault Pro"],
    ["500 string", new RelayError(500, { detail: "inventory_unknown" }, "inventory_unknown"), "inventory_unknown"],
    ["{error, message}", new RelayError(409, { detail: { error: "busy", message: "Try later." } }, "Try later."), "Try later."],
    ["object detail without a sentence", new RelayError(404, { detail: { error: "sequence_not_found" } },
      '{"error":"sequence_not_found"}'), GENERIC_REFUSAL],
    ["array detail", new RelayError(422, { detail: [{ loc: ["body"], msg: "field required" }] }, "field required"),
      GENERIC_REFUSAL],
    ["bare HTTP 500 (empty body)", new RelayError(500, "", "HTTP 500"), GENERIC_REFUSAL],
    ["non-JSON body", new RelayError(502, "<html>Bad Gateway</html>", "<html>Bad Gateway</html>"), GENERIC_REFUSAL],
    ["network error", new TypeError("Failed to fetch"), "Could not reach the relay."],
  ])("refusalText: %s", (_n, err, want) => {
    expect(refusalText(err)).toBe(want);
    expect(refusalText(err)).not.toMatch(/^HTTP \d|[{}<]/);
  });

  it.each<[string, unknown, string]>([
    ["404 sequence_not_found", new RelayError(404, { detail: { error: "sequence_not_found" } }, '{"error":"sequence_not_found"}'),
      "This sequence has no steps any more. It was renamed or deleted: reload the page."],
    ["503 inventory_unknown", new RelayError(503, { detail: { error: "inventory_unknown" } }, '{"error":"inventory_unknown"}'),
      "The vault list could not be read just now. Try again in a minute."],
    ["400 account_id_required", new RelayError(400, { detail: { error: "account_id_required" } },
      '{"error":"account_id_required"}'), "Pick a Creator first."],
    ["403 folder_not_allowed", new RelayError(403, { detail: { error: "folder_not_allowed" } }, '{"error":"folder_not_allowed"}'),
      ASK_OWNER],
    ["an unknown code", new RelayError(500, { detail: { error: "boom" } }, '{"error":"boom"}'), GENERIC_REFUSAL],
    ["bare HTTP 500", new RelayError(500, "", "HTTP 500"), GENERIC_REFUSAL],
    ["a string detail", new RelayError(403, { detail: "Your role does not allow Vault Pro" }, "x"),
      "Your role does not allow Vault Pro"],
    ["network error", new TypeError("Failed to fetch"), "Could not reach the relay."],
  ])("fillRefusalText: %s", (_n, err, want) => {
    expect(fillRefusalText(err)).toBe(want);
    expect(fillRefusalText(err)).not.toMatch(/^HTTP \d|[{}]/);
  });

  it("reads the fresh plan off a 409 stale only", () => {
    const fresh = plan("ok");
    expect(stalePlan(new RelayError(409, { detail: { error: "stale", plan: fresh } }))).toBe(fresh);
    expect(stalePlan(new RelayError(409, { detail: { error: "describe_already_running" } }))).toBeNull();
    expect(stalePlan(new Error("x"))).toBeNull();
  });
});

describe("canDescribe", () => {
  it.each<[string, FillPlan | null, boolean]>([
    ["offer", plan("not_enough_content"), true],
    ["blocked", plan("not_enough_content", { describe: { described: 1, target: 9, remaining: 8, can_describe: false, blocked_reason: "cap" } }), false],
    ["nothing left", plan("not_enough_content", { describe: { described: 9, target: 9, remaining: 0, can_describe: false, blocked_reason: null } }), false],
    ["other status", plan("no_fit"), false],
    ["no plan", null, false],
  ])("%s", (_n, p, want) => expect(canDescribe(p)).toBe(want));
});

describe("dialogFor", () => {
  const NOW = Date.parse("2026-11-21T12:00:00Z");
  const IDLE: SweepView = { running: false, progress: null };
  const OFFER = "This sequence needs more described vault content. Describe up to 1,000 items for this Creator? 120 of 1000 done.";
  const BLOCKED = plan("not_enough_content", {
    describe: { described: 300, target: 1000, remaining: 700, can_describe: false, blocked_reason: "Today's AI budget is spent." },
  });
  const EMPTY = plan("not_enough_content", {
    describe: { described: 40, target: 40, remaining: 0, can_describe: false, blocked_reason: null },
  });
  const CONFLICT = plan("price_conflict", {
    conflict: { step: 3, rule: "below_earlier", price_cents: 1000 },
    options: [opt({ id: 1, step: 2, price_cents: 2000, price_fixed: true }), opt({ id: 2, step: 3, price_cents: 1000, price_fixed: true })],
  });
  const RANGE = plan("price_out_of_range", { conflict: { step: 4, rule: "under_min", price_cents: 200 } });

  type Row = [string, FillPlan, { title: string; lines: string[]; button: "describe" | "fill" | null }];
  const byStatus: Row[] = [
    ["ok → Ready", plan("ok"), { title: "Fill with content", lines: ["Ready to fill."], button: "fill" }],
    ["not_enough_content, can describe → offer", plan("not_enough_content"),
      { title: "Describe content first?", lines: [OFFER], button: "describe" }],
    ["not_enough_content, blocked → its sentence", BLOCKED, { title: "Fill with content", lines: [
      "This sequence needs more described vault content. 300 of 1000 done.", "Today's AI budget is spent."], button: null }],
    ["not_enough_content, nothing left", EMPTY, { title: "Fill with content", lines: [
      "Not enough content. 40 of 40 items are described and there is nothing left to describe."], button: null }],
    ["not_enough_content, left but can't describe, no reason → the count only", plan("not_enough_content", {
      describe: { described: 300, target: 1000, remaining: 700, can_describe: false, blocked_reason: null },
    }), { title: "Fill with content", lines: [
      "This sequence needs more described vault content. 300 of 1000 done."], button: null }],
    ["no_fit", plan("no_fit"), { title: "Fill with content",
      lines: ["This Creator's described content cannot fill every paid step of this sequence."], button: null }],
    ["no_paid_steps", plan("no_paid_steps"), { title: "Fill with content",
      lines: ["No step in this sequence sells anything yet. Put a price on the steps that sell, then fill again."], button: null }],
    ["price_conflict", CONFLICT, { title: "Fill with content",
      lines: ["Step 3 is priced below step 2 — fix the price, then fill again."], button: null }],
    ["price_out_of_range", RANGE, { title: "Fill with content",
      lines: ["Step 4: $2 is under OnlyFans' $3 minimum — fix the price, then fill again."], button: null }],
    ["already_filled", plan("already_filled"), { title: "Fill with content",
      lines: ["Every step already has its content."], button: null }],
    ["already_filled with an empty free step (free_unfilled) → says the free step stays empty", plan("already_filled", {
      options: [opt({ id: 1, step: 1, role: "free_media", flags: ["free_unfilled"] }), opt({ id: 2, step: 2, keep: true, media: [9] })],
    }), { title: "Fill with content", lines: [
      "Every paid step already has its content. No photo left is safe to send free, so the free steps stay empty."], button: null }],
    ["reserved", plan("reserved"), { title: "Fill with content",
      lines: ["This sequence is generated by a script source and is not filled."], button: null }],
  ];

  it.each(byStatus)("no sweep: %s", (_n, p, want) => {
    const d = dialogFor({ status: p.status, plan: p, sweep: IDLE, refusal: null, now: NOW });
    expect({ title: d.title, lines: d.lines, button: d.button }).toEqual(want);
    expect(d.note).toBeNull();
    expect(d.lines.join(" ")).not.toMatch(/total|estimate/i);
  });

  const settled: Array<[string, SweepView["progress"], string]> = [
    ["stop", { total: 50, done: 9, stop: { message: "Stopped: 25 items in a row failed.", fix: "Fix it, then press again." } },
      "Stopped: 25 items in a row failed."],
    ["key", { total: 50, done: 1, key_error: { error: "api_key_invalid", feature: "describe_media", provider: "typesafe",
      fix_url: "/settings", message: "Key rejected", fix: "Paste a new one" } }, "Key rejected"],
    ["death", { total: 50, done: 20, aborted: true }, "Stopped early — 30 left. Press again to resume."],
    ["recent failures", { total: 50, done: 50, failed: 5, finished_at: "2026-11-21T11:00:00Z" }, "5 of 50 failed."],
  ];
  it.each(settled.flatMap(([kind, progress, text]) => byStatus.map(([n, p, want]) => [`${kind} × ${n}`, progress, text, p, want] as const)))(
    "settled sweep, %s: the note sits above the plan's state", (_n, progress, text, p, want) => {
      const d = dialogFor({ status: p.status, plan: p, sweep: { running: false, progress }, refusal: null, now: NOW });
      expect(d.note?.text).toContain(text);
      expect({ title: d.title, lines: d.lines, button: d.button }).toEqual(want);
    });

  it.each(byStatus)("running sweep wins over %s: progress, counts from the plan", (_n, p) => {
    const d = dialogFor({
      status: p.status, plan: p, refusal: null, now: NOW,
      sweep: { running: true, progress: { total: 900, done: 212, failed: 3, error: "boom" } },
    });
    expect(d.title).toBe("Describing content");
    expect(d.lines).toEqual([
      "Checked 212 of 900. Keeps going if you close this.",
      "3 could not be described.",
      "First error: boom",
      `${p.describe.described} of ${p.describe.target} described.`,
    ]);
    expect(d.button).toBeNull();
  });

  it("running before the first snapshot, or only starting: starting…", () => {
    expect(dialogFor({ status: null, plan: undefined, refusal: null, sweep: { running: true, progress: null }, now: NOW }).lines)
      .toEqual(["starting…"]);
    expect(dialogFor({ status: null, plan: undefined, refusal: null, sweep: { running: false, starting: true, progress: null }, now: NOW }).lines)
      .toEqual(["starting…"]);
  });

  it.each(byStatus)("a refusal wins over %s and a running sweep", (_n, p) => {
    for (const sweep of [IDLE, { running: true, progress: { total: 9, done: 1 } }]) {
      const d = dialogFor({ status: p.status, plan: p, sweep, refusal: "Your role does not allow Vault Pro", now: NOW });
      expect(d).toEqual({ title: "Fill with content", lines: ["Your role does not allow Vault Pro"], note: null, button: null });
    }
  });

  it("before the plan loads, the apply answer's status speaks", () => {
    expect(dialogFor({ status: "no_fit", plan: undefined, sweep: IDLE, refusal: null, now: NOW }).lines)
      .toEqual(["This Creator's described content cannot fill every paid step of this sequence."]);
  });
});
