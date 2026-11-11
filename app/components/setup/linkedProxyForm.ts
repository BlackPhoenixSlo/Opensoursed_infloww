/**
 * linkedProxyForm — LinkedCreatorProxy's optional "add your proxy" editor as a pure reducer: the draft, the open fold,
 * the fallback checkbox, the run in flight and its recorded outcome, plus `canSubmit`, `buildBody` (POST
 * /admin/proxies) and the copy each outcome shows. The component only dispatches; the relay calls (the switch and
 * what each failure does) are `linkedProxyRun`'s.
 *
 * The fallback checkbox (on by default) only decides what a failed TEST does: on, the form folds and says where the
 * creator stays; off, the form stays open with the error. The run takes the box as it was at Connect, and the copy
 * reads the recorded outcome, never the live box.
 */

import { EMPTY_DRAFT, draftLabel, draftProblem, type ProxyDraft } from "./AddProxyModal";
import type { ProxyChoice } from "./proxyApi";
import { BRAND_NAME } from "@/lib/brand";

/** Where the creator stays when the new proxy fails its test. `bind`: it is on none and the pool has proxies, so the
 *  fallback puts it on the pool. */
export type Keep = { kind: "pool"; bind: boolean } | { kind: "custom"; label: string } | { kind: "none" };

/** A run that finished with the account where it should be. */
export type Done =
  /** Assigned and the session reloaded through it. */
  | { kind: "connected"; label: string }
  /** The test failed with the fallback on: the candidate is deleted and the creator stays on `keep` (an account on
   *  none was put on the pool and its session reloaded). */
  | { kind: "kept"; keep: Keep; testError: string; cleanupError: string | null };

export type Outcome =
  | Done
  /** Nothing changed on the account (or nothing more than said): the form stays open with `text`. */
  | { kind: "failed"; text: string }
  /** The binding is in place (`done` says which), but the session refresh failed: Retry reloads only, and its
   *  success is `done`. */
  | { kind: "reloadFailed"; done: Done; error: string };

export interface LinkedProxyState {
  draft: ProxyDraft;
  open: boolean;
  fallback: boolean;
  busy: boolean;
  /** The last run's result (its copy records which branch the box chose at Connect). */
  outcome: Outcome | null;
}

export type LinkedProxyAction =
  | { type: "toggle" }
  | { type: "edit"; patch: Partial<ProxyDraft> }
  | { type: "setFallback"; value: boolean }
  | { type: "submitStart" }
  /** Retry the session refresh after `reloadFailed`. */
  | { type: "retryStart" }
  | { type: "settled"; outcome: Outcome };

const BLANK: ProxyDraft = { ...EMPTY_DRAFT, scheme: "http" };

export const INITIAL_LINKED_PROXY: LinkedProxyState = {
  draft: BLANK, open: false, fallback: true, busy: false, outcome: null,
};

export function linkedProxyReducer(state: LinkedProxyState, action: LinkedProxyAction): LinkedProxyState {
  switch (action.type) {
    case "toggle":
      return state.busy ? state : { ...state, open: !state.open };
    case "edit":
      return state.busy ? state : { ...state, draft: { ...state.draft, ...action.patch } };
    case "setFallback":
      return state.busy || state.fallback === action.value ? state : { ...state, fallback: action.value };
    case "submitStart":
      return state.busy ? state : { ...state, busy: true, outcome: null };
    case "retryStart":
      return state.busy || state.outcome?.kind !== "reloadFailed" ? state : { ...state, busy: true };
    case "settled":
      if (!state.busy) return state;
      // A failure keeps the form open with what was typed; anything that touched the account folds it.
      return action.outcome.kind === "failed"
        ? { ...state, busy: false, outcome: action.outcome }
        : { ...state, busy: false, outcome: action.outcome, draft: BLANK, open: false };
  }
}

/** May Connect go: not while a run is in flight, and the draft is complete and its label free. */
export const canSubmit = (s: LinkedProxyState, takenLabels: readonly string[] | null): boolean =>
  !s.busy && !draftProblem(s.draft, takenLabels);

/** POST /admin/proxies's body for the draft. */
export function buildBody(d: ProxyDraft) {
  return {
    label: draftLabel(d).trim(), scheme: d.scheme, host: d.host.trim(), port: Number(d.port),
    username: d.username.trim() || null, password: d.password || null,
  };
}

/** Where a failed test leaves the creator, from its current proxy and the pool's size. */
export function keepTarget(current: ProxyChoice, poolSize: number): Keep {
  if (current.type === "infloww") return { kind: "pool", bind: false };
  if (current.type === "custom") return { kind: "custom", label: current.label };
  return poolSize > 0 ? { kind: "pool", bind: true } : { kind: "none" };
}

export function keepText(k: Keep): string {
  if (k.kind === "pool") return `${BRAND_NAME}'s default proxy`;
  if (k.kind === "custom") return `its current proxy (${k.label})`;
  return "no proxy (the server's IP)";
}

/** The fallback checkbox's label. */
export const fallbackLabel = (k: Keep) => `If my proxy fails its test, keep this creator on ${keepText(k)}`;

const cleanupNote = (cleanupError: string | null) =>
  cleanupError ? ` Couldn't remove the failed proxy (${cleanupError}); delete it under Custom proxy.` : "";

/** A failed test with the fallback off: the form stays open. */
export const failedTestText = (testError: string, cleanupError: string | null) =>
  `Your proxy failed its test (${testError}). Check its details and try again.${cleanupNote(cleanupError)}`;

/** The line an outcome shows. */
export function outcomeMessage(o: Outcome): { tone: "ok" | "warn" | "err"; text: string } {
  switch (o.kind) {
    case "connected":
      return { tone: "ok", text: "Your proxy is connected." };
    case "kept":
      return {
        tone: "warn",
        text: `Your proxy failed its test (${o.testError}). This creator stays on ${keepText(o.keep)}.${cleanupNote(o.cleanupError)}`,
      };
    case "failed":
      return { tone: "err", text: o.text };
    case "reloadFailed": {
      const refresh = `but the session refresh failed (${o.error}). Retry the refresh.`;
      const d = o.done;
      return d.kind === "connected"
        ? { tone: "warn", text: `Proxy ${d.label} is assigned, ${refresh}` }
        : {
          tone: "warn",
          text: `Your proxy failed its test (${d.testError}). This creator is now on ${keepText(d.keep)}, ${refresh}${cleanupNote(d.cleanupError)}`,
        };
    }
  }
}
