import { describe, expect, it } from "vitest";

import {
  buildPayload, canSend, errorText, initialSupportState, MAX_SUPPORT_CHARS, messagesOf, NO_SUPPORT,
  SUPPORT_FALLBACK_ERROR, supportReducer, supportStatusOf, type SupportAction, type SupportMessage, type SupportState,
} from "./supportReducer";

const run = (actions: SupportAction[], from: SupportState = initialSupportState) => actions.reduce(supportReducer, from);
const msg = (id: number, from: "me" | "support" = "me", text = `m${id}`): SupportMessage => ({ id, from, text, at: "" });
const ready = run([{ type: "loaded", messages: [msg(1)] }]);

describe("supportStatusOf", () => {
  it.each<[string, unknown, typeof NO_SUPPORT]>([
    ["not configured", { configured: false }, NO_SUPPORT],
    ["unrelated mock body", { count: 0, list: [] }, NO_SUPPORT],
    ["null", null, NO_SUPPORT],
    ["configured, none", { configured: true, unread: 0 }, { configured: true, unread: 0 }],
    ["configured, two", { configured: true, unread: 2 }, { configured: true, unread: 2 }],
    ["configured, junk count", { configured: true, unread: "3" }, { configured: true, unread: 0 }],
    ["configured, negative", { configured: true, unread: -1 }, { configured: true, unread: 0 }],
  ])("%s", (_n, body, want) => expect(supportStatusOf(body)).toEqual(want));
});

describe("messagesOf", () => {
  it("keeps well-formed rows and maps anything not support to me", () => {
    expect(messagesOf({ messages: [
      { id: 1, from: "me", text: "a", at: "t" }, { id: 2, from: "support", text: "b" },
      { id: 3, from: "evil", text: "c", at: "t" }, { id: "4", text: "d" }, null, { id: 5 },
    ] })).toEqual([
      { id: 1, from: "me", text: "a", at: "t" }, { id: 2, from: "support", text: "b", at: "" },
      { id: 3, from: "me", text: "c", at: "t" },
    ]);
  });
  it.each([undefined, null, {}, { messages: "x" }])("no list → empty (%s)", (body) => expect(messagesOf(body)).toEqual([]));
});

describe("supportReducer", () => {
  it.each<[string, SupportAction[], Partial<SupportState>]>([
    ["load then type", [{ type: "loaded", messages: [msg(1)] }, { type: "draft", text: "hi" }],
      { phase: "ready", draft: "hi", messages: [msg(1)] }],
    ["first load failing shows the error", [{ type: "load_failed", error: "down" }], { phase: "failed", error: "down" }],
    ["retry after a failed load", [{ type: "load_failed", error: "down" }, { type: "load_started" }],
      { phase: "loading", error: null }],
    ["a failed reload keeps the thread", [{ type: "loaded", messages: [msg(1)] }, { type: "load_failed", error: "down" }],
      { phase: "ready", messages: [msg(1)], error: "down" }],
    ["send clears the draft and takes the hub's thread",
      [{ type: "loaded", messages: [] }, { type: "draft", text: "x" }, { type: "send_started" },
        { type: "sent", messages: [msg(1), msg(2, "support")] }],
      { draft: "", sending: false, messages: [msg(1), msg(2, "support")] }],
    ["a failed send keeps the draft to retry",
      [{ type: "loaded", messages: [] }, { type: "draft", text: "x" }, { type: "send_started" }, { type: "send_failed", error: "e" }],
      { draft: "x", sending: false, error: "e" }],
  ])("%s", (_n, actions, want) => expect(run(actions)).toMatchObject(want));

  it("draft is capped at the hub's limit", () => {
    expect(run([{ type: "draft", text: "a".repeat(MAX_SUPPORT_CHARS + 50) }]).draft).toHaveLength(MAX_SUPPORT_CHARS);
  });

  it("send_started is a no-op when sending is not allowed", () => {
    expect(supportReducer(ready, { type: "send_started" })).toBe(ready);
  });

  it("load_started while already loaded changes nothing", () => {
    expect(supportReducer(ready, { type: "load_started" })).toBe(ready);
  });
});

describe("canSend / buildPayload", () => {
  it.each<[string, SupportState, boolean]>([
    ["still loading", { ...initialSupportState, draft: "x" }, false],
    ["blank", { ...ready, draft: "   " }, false],
    ["in flight", { ...ready, draft: "x", sending: true }, false],
    ["ready", { ...ready, draft: "x" }, true],
    ["after a failed load", { ...initialSupportState, phase: "failed", draft: "x" }, true],
  ])("%s", (_n, s, want) => expect(canSend(s)).toBe(want));

  it("payload is only the trimmed text", () => {
    expect(buildPayload({ ...ready, draft: "  need bulk tags \n" })).toEqual({ text: "need bulk tags" });
  });
});

describe("errorText", () => {
  it.each<[string, unknown, string]>([
    ["relay detail string", { body: { detail: "Support is unreachable right now — try again soon." } },
      "Support is unreachable right now — try again soon."],
    ["object detail", { body: { detail: { error: "x" } } }, SUPPORT_FALLBACK_ERROR],
    ["plain error", new Error("boom"), SUPPORT_FALLBACK_ERROR],
    ["null", null, SUPPORT_FALLBACK_ERROR],
  ])("%s", (_n, e, want) => expect(errorText(e)).toBe(want));
});
