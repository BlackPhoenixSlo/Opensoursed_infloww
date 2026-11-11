import { describe, expect, it } from "vitest";

import {
  INITIAL_LINKED_PROXY, buildBody, canSubmit, fallbackLabel, keepTarget, linkedProxyReducer, outcomeMessage,
  type LinkedProxyAction, type LinkedProxyState, type Outcome,
} from "./linkedProxyForm";
import { BRAND_NAME } from "@/lib/brand";

const FILLED = { ...INITIAL_LINKED_PROXY.draft, host: " proxy.example ", port: "8080" };
const S = (over: Partial<LinkedProxyState> = {}): LinkedProxyState => ({ ...INITIAL_LINKED_PROXY, ...over });
const run = (s: LinkedProxyState, ...a: LinkedProxyAction[]) => a.reduce(linkedProxyReducer, s);
const settled = (outcome: Outcome) => ({ type: "settled", outcome }) as const;
const KEPT: Outcome = { kind: "kept", keep: { kind: "custom", label: "old" }, testError: "e", cleanupError: null };

describe("linkedProxyReducer", () => {
  it.each<[string, LinkedProxyState, LinkedProxyAction[], Partial<LinkedProxyState>]>([
    ["toggle opens", S(), [{ type: "toggle" }], { open: true }],
    ["edit patches the draft", S({ open: true }), [{ type: "edit", patch: { host: "h" } }], { draft: { ...INITIAL_LINKED_PROXY.draft, host: "h" } }],
    ["fallback off", S(), [{ type: "setFallback", value: false }], { fallback: false }],
    ["submit: busy, the last outcome goes", S({ outcome: { kind: "failed", text: "x" } }), [{ type: "submitStart" }], { busy: true, outcome: null }],
    ["connected folds and clears", S({ open: true, draft: FILLED, busy: true }), [settled({ kind: "connected", label: "l" })],
      { busy: false, open: false, draft: INITIAL_LINKED_PROXY.draft, outcome: { kind: "connected", label: "l" } }],
    ["kept folds and clears", S({ open: true, draft: FILLED, busy: true }),
      [settled(KEPT)], { busy: false, open: false, draft: INITIAL_LINKED_PROXY.draft, outcome: KEPT }],
    ["failed keeps the form and what was typed", S({ open: true, draft: FILLED, busy: true }), [settled({ kind: "failed", text: "t" })],
      { busy: false, open: true, draft: FILLED, outcome: { kind: "failed", text: "t" } }],
    ["retry after a failed refresh", S({ outcome: { kind: "reloadFailed", done: { kind: "connected", label: "l" }, error: "e" } }), [{ type: "retryStart" }], { busy: true }],
  ])("%s", (_, s, actions, want) => {
    expect(run(s, ...actions)).toEqual({ ...s, ...want });
  });

  it.each<[string, LinkedProxyState, LinkedProxyAction]>([
    ["toggle while busy", S({ busy: true, open: true }), { type: "toggle" }],
    ["edit while busy", S({ busy: true }), { type: "edit", patch: { host: "x" } }],
    ["fallback while busy", S({ busy: true }), { type: "setFallback", value: false }],
    ["fallback unchanged", S(), { type: "setFallback", value: true }],
    ["a second submit", S({ busy: true }), { type: "submitStart" }],
    ["retry with nothing to retry", S({ outcome: { kind: "connected", label: "l" } }), { type: "retryStart" }],
    ["settled without a run", S(), settled({ kind: "connected", label: "l" })],
  ])("refused (same state): %s", (_, s, a) => {
    expect(linkedProxyReducer(s, a)).toBe(s);
  });
});

describe("canSubmit / buildBody", () => {
  it.each<[string, LinkedProxyState, readonly string[] | null, boolean]>([
    ["complete", S({ draft: FILLED }), [], true],
    ["list not loaded", S({ draft: FILLED }), null, false],
    ["duplicate label", S({ draft: FILLED }), ["proxy.example:8080"], false],
    ["no host", S(), [], false],
    ["busy", S({ draft: FILLED, busy: true }), [], false],
  ])("%s", (_, s, taken, ok) => expect(canSubmit(s, taken)).toBe(ok));

  it("trims, labels host:port, blanks are null", () => {
    expect(buildBody(FILLED)).toEqual({
      label: "proxy.example:8080", scheme: "http", host: "proxy.example", port: 8080, username: null, password: null,
    });
  });
});

describe("where a failed test leaves the creator", () => {
  it.each<[string, Parameters<typeof keepTarget>[0], number, string]>([
    ["on the pool", { type: "infloww" }, 2, `If my proxy fails its test, keep this creator on ${BRAND_NAME}'s default proxy`],
    ["on a custom proxy", { type: "custom", label: "old", ok: true }, 2, "If my proxy fails its test, keep this creator on its current proxy (old)"],
    ["on none, pool has proxies", { type: "none" }, 2, `If my proxy fails its test, keep this creator on ${BRAND_NAME}'s default proxy`],
    ["on none, no pool", { type: "none" }, 0, "If my proxy fails its test, keep this creator on no proxy (the server's IP)"],
  ])("%s", (_, current, pool, label) => expect(fallbackLabel(keepTarget(current, pool))).toBe(label));

  it("only an unbound account with a pool gets the pool bound", () => {
    expect(keepTarget({ type: "none" }, 3)).toEqual({ kind: "pool", bind: true });
    expect(keepTarget({ type: "infloww" }, 3)).toEqual({ kind: "pool", bind: false });
  });
});

describe("outcomeMessage", () => {
  it.each<[string, Outcome, string, string]>([
    ["connected", { kind: "connected", label: "l" }, "ok", "Your proxy is connected."],
    ["kept on a custom proxy", { kind: "kept", keep: { kind: "custom", label: "old" }, testError: "timeout", cleanupError: null },
      "warn", "Your proxy failed its test (timeout). This creator stays on its current proxy (old)."],
    ["kept, cleanup failed", { kind: "kept", keep: { kind: "none" }, testError: "timeout", cleanupError: "409" },
      "warn", "Your proxy failed its test (timeout). This creator stays on no proxy (the server's IP). Couldn't remove the failed proxy (409); delete it under Custom proxy."],
    ["failed", { kind: "failed", text: "boom" }, "err", "boom"],
    ["refresh failed", { kind: "reloadFailed", done: { kind: "connected", label: "l" }, error: "502" }, "warn", "Proxy l is assigned, but the session refresh failed (502). Retry the refresh."],
    ["pool fallback bound, refresh failed", { kind: "reloadFailed", done: { kind: "kept", keep: { kind: "pool", bind: true }, testError: "t", cleanupError: "c" }, error: "502" }, "warn",
      `Your proxy failed its test (t). This creator is now on ${BRAND_NAME}'s default proxy, but the session refresh failed (502). Retry the refresh. Couldn't remove the failed proxy (c); delete it under Custom proxy.`],
  ])("%s", (_, o, tone, text) => expect(outcomeMessage(o)).toEqual({ tone, text }));
});
