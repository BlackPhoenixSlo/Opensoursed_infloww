import { EMPTY_DRAFT, draftLabel, draftProblem, type ProxyDraft } from "./AddProxyModal";
import type { ProxyChoice } from "./proxyApi";
import { BRAND_NAME } from "@/lib/brand";

export type Keep = { kind: "pool"; bind: boolean } | { kind: "custom"; label: string } | { kind: "none" };

export type Done =
  | { kind: "connected"; label: string }
  | { kind: "kept"; keep: Keep; testError: string; cleanupError: string | null };

export type Outcome =
  | Done
  | { kind: "failed"; text: string }
  | { kind: "reloadFailed"; done: Done; error: string };

export interface LinkedProxyState {
  draft: ProxyDraft;
  open: boolean;
  fallback: boolean;
  busy: boolean;
  outcome: Outcome | null;
}

export type LinkedProxyAction =
  | { type: "toggle" }
  | { type: "edit"; patch: Partial<ProxyDraft> }
  | { type: "setFallback"; value: boolean }
  | { type: "submitStart" }
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
      return action.outcome.kind === "failed"
        ? { ...state, busy: false, outcome: action.outcome }
        : { ...state, busy: false, outcome: action.outcome, draft: BLANK, open: false };
  }
}

export const canSubmit = (s: LinkedProxyState, takenLabels: readonly string[] | null): boolean =>
  !s.busy && !draftProblem(s.draft, takenLabels);

export function buildBody(d: ProxyDraft) {
  return {
    label: draftLabel(d).trim(), scheme: d.scheme, host: d.host.trim(), port: Number(d.port),
    username: d.username.trim() || null, password: d.password || null,
  };
}

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

export const fallbackLabel = (k: Keep) => `If my proxy fails its test, keep this creator on ${keepText(k)}`;

const cleanupNote = (cleanupError: string | null) =>
  cleanupError ? ` Couldn't remove the failed proxy (${cleanupError}); delete it under Custom proxy.` : "";

export const failedTestText = (testError: string, cleanupError: string | null) =>
  `Your proxy failed its test (${testError}). Check its details and try again.${cleanupNote(cleanupError)}`;

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
