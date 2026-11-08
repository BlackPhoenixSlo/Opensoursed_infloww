import { describe, expect, it } from "vitest";

import {
  BUSY_REASON, buildPayload, canSubmit, type FailedBubble, outcomeOf, planSubmit, QUICK_REPLY_EMPTY, quickReplyReducer,
  type QuickReplyState,
} from "@/components/quickReply";

const S = (p: Partial<QuickReplyState>): QuickReplyState => ({ ...QUICK_REPLY_EMPTY, ...p });

describe("quickReplyReducer", () => {
  it.each([
    { name: "typing sets the line", from: S({}), a: { type: "type", text: "hi" } as const, to: S({ text: "hi" }) },
    { name: "typing is held while sending", from: S({ text: "hi", sending: true }), a: { type: "type", text: "x" } as const, to: S({ text: "hi", sending: true }) },
    { name: "submit starts a send and drops the last outcome", from: S({ text: "hi", outcome: { ok: true } }), a: { type: "submit" } as const, to: S({ text: "hi", sending: true }) },
    { name: "submit of a blank line does nothing", from: S({ text: "  " }), a: { type: "submit" } as const, to: S({ text: "  " }) },
    { name: "a second submit while sending does nothing", from: S({ text: "hi", sending: true }), a: { type: "submit" } as const, to: S({ text: "hi", sending: true }) },
    { name: "sent clears the line", from: S({ text: "hi", sending: true }), a: { type: "settled", outcome: { ok: true } } as const, to: S({ outcome: { ok: true } }) },
    { name: "failed keeps the line", from: S({ text: "hi", sending: true }), a: { type: "settled", outcome: { ok: false, reason: "No." } } as const, to: S({ text: "hi", outcome: { ok: false, reason: "No." } }) },
    { name: "failed remembers its bubble and line", from: S({ text: " hi ", sending: true }), a: { type: "settled", outcome: { ok: false, reason: "No." }, tempId: -3 } as const, to: S({ text: " hi ", outcome: { ok: false, reason: "No." }, failed: { tempId: -3, text: "hi" } }) },
    { name: "sent forgets the failed bubble", from: S({ text: "hi", sending: true, failed: { tempId: -3, text: "hi" } }), a: { type: "settled", outcome: { ok: true }, tempId: -3 } as const, to: S({ outcome: { ok: true } }) },
    { name: "done (sent from the Thread) clears all", from: S({ text: "hi", outcome: { ok: false, reason: "No." }, failed: { tempId: -3, text: "hi" } }), a: { type: "done" } as const, to: S({}) },
    { name: "busy says so, keeps line and bubble", from: S({ text: "hi", failed: { tempId: -3, text: "hi" } }), a: { type: "busy" } as const, to: S({ text: "hi", outcome: { ok: false, reason: BUSY_REASON }, failed: { tempId: -3, text: "hi" } }) },
    { name: "typing keeps the failed bubble", from: S({ text: "hi", failed: { tempId: -3, text: "hi" } }), a: { type: "type", text: "yo" } as const, to: S({ text: "yo", failed: { tempId: -3, text: "hi" } }) },
  ])("$name", ({ from, a, to }) => {
    expect(quickReplyReducer(from, a)).toEqual(to);
  });
});

describe("canSubmit / buildPayload", () => {
  it.each([
    { s: S({ text: "hi" }), ok: true },
    { s: S({ text: "   " }), ok: false },
    { s: S({ text: "hi", sending: true }), ok: false },
  ])("canSubmit $s.text sending $s.sending: $ok", ({ s, ok }) => {
    expect(canSubmit(s)).toBe(ok);
  });
  it("sends the trimmed line", () => {
    expect(buildPayload(S({ text: "  hi  " }))).toEqual({ text: "hi" });
  });
});

describe("planSubmit", () => {
  const failed = { tempId: -3, text: "hi" };
  const B = (p: Partial<FailedBubble>): FailedBubble => ({ stashed: false, delivered: false, pending: false, ...p });
  it.each([
    { name: "no failed bubble: send", s: S({ text: "hi" }), b: B({ stashed: true }), plan: { kind: "send", payload: { text: "hi" } } },
    { name: "same line again: retry the failed bubble", s: S({ text: " hi ", failed }), b: B({ stashed: true }), plan: { kind: "retry", tempId: -3 } },
    { name: "another line: replace the failed bubble", s: S({ text: "yo", failed }), b: B({ stashed: true }), plan: { kind: "replace", tempId: -3, payload: { text: "yo" } } },
    { name: "Thread Retry in flight, same line: busy, no send", s: S({ text: "hi", failed }), b: B({ stashed: true, pending: true }), plan: { kind: "busy" } },
    { name: "Thread Retry in flight, another line: plain send", s: S({ text: "yo", failed }), b: B({ stashed: true, pending: true }), plan: { kind: "send", payload: { text: "yo" } } },
    { name: "Thread Retry sent it, same line: done, no send", s: S({ text: "hi", failed }), b: B({ delivered: true }), plan: { kind: "done" } },
    { name: "Thread Retry sent it, another line: plain send", s: S({ text: "yo", failed }), b: B({ delivered: true }), plan: { kind: "send", payload: { text: "yo" } } },
    { name: "Thread discarded it, same line: plain send (not done)", s: S({ text: "hi", failed }), b: B({}), plan: { kind: "send", payload: { text: "hi" } } },
    { name: "Thread discarded it, another line: plain send", s: S({ text: "yo", failed }), b: B({}), plan: { kind: "send", payload: { text: "yo" } } },
  ])("$name", ({ s, b, plan }) => {
    expect(planSubmit(s, b)).toEqual(plan);
  });
});

describe("outcomeOf", () => {
  it.each([
    { name: "sent", ended: { sent: true } as const, out: { ok: true } },
    { name: "failed with a reason", ended: { sent: false, failure: { reason: "Fan blocked you" } } as const, out: { ok: false, reason: "Fan blocked you" } },
    { name: "discarded mid-way (no failure) is not Sent", ended: { sent: false } as const, out: { ok: false, reason: "Send failed." } },
    { name: "refused (no chat)", ended: undefined, out: { ok: false, reason: "Send failed." } },
    { name: "thrown", ended: { error: new Error("offline") }, out: { ok: false, reason: "offline" } },
  ])("$name", ({ ended, out }) => {
    expect(outcomeOf(ended)).toEqual(out);
  });
});
