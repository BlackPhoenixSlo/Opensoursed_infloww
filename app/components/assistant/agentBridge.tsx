"use client";

/**
 * The agent bridge: how the help bot's "Do it for me" runner (useDoRunner.ts) reaches a page's own form without a
 * DOM loop. The page registers what a person's clicks would call — ReadyMadePanel its `openNew`, ReadyMadeRuleEditor
 * its reducer `dispatch` and its agent save (the Create button's own canSave gate and request, with Enabled FORCED
 * off whatever was dispatched) — and unregisters on unmount. The runner waits for a registration (`waitFor`), then calls them.
 * One handle object per mounted component, made once and read live through refs: StrictMode (next dev) re-runs the
 * register effect (unregister + register again), and the runner holding the handle must still see the same one —
 * a different handle means a different editor (a remount, its state gone).
 *
 * Provided by AssistantProvider; with no provider (a page rendered alone, its tests) the hooks are no-ops.
 */

import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import type { RuleEditorAction } from "@/components/automations/ruleEditorForm";
import type { Kind } from "@/components/compose/payloadRules";

export type SaveResult = { ok: true } | { ok: false; reason: string };

export interface PanelHandle {
  readonly kind: Kind;
  /** The page's creator (null while it resolves: New is off then). */
  readonly accountId: string | null;
  openNew: () => void;
}

export interface EditorHandle {
  readonly kind: Kind;
  readonly accountId: string;
  /** A new rule's editor (the agent never edits a saved one). */
  readonly isNew: boolean;
  dispatch: (a: RuleEditorAction) => void;
  /** The editor's agent save (Enabled forced off), once every dispatch so far has rendered; never a save of state
   *  that hasn't (SAVE_WAIT_MS → not saved). */
  save: () => Promise<SaveResult>;
}

export interface AgentBridge {
  registerPanel: (h: PanelHandle) => () => void;
  registerEditor: (h: EditorHandle) => () => void;
  panel: (kind: Kind, accountId: string) => PanelHandle | null;
  /** The open NEW editor of `kind` on `accountId`. */
  editor: (kind: Kind, accountId: string) => EditorHandle | null;
  /** Any rule editor is open (new or edit, any page): a run never fills over, nor navigates away from, one. */
  hasEditor: () => boolean;
  /** Resolves with `pick()`'s first non-null value (checked now and on every registration), rejects after `ms` or on
   *  `signal`. */
  waitFor: <T>(pick: () => T | null, ms: number, signal: AbortSignal) => Promise<T>;
}

export function createAgentBridge(): AgentBridge {
  const panels = new Set<PanelHandle>();
  const editors = new Set<EditorHandle>();
  const listeners = new Set<() => void>();
  const changed = () => listeners.forEach((f) => f());
  const add = <H,>(set: Set<H>, h: H) => {
    set.add(h);
    changed();
    return () => { set.delete(h); changed(); };
  };
  return {
    registerPanel: (h) => add(panels, h),
    registerEditor: (h) => add(editors, h),
    panel: (kind, accountId) => [...panels].find((p) => p.kind === kind && p.accountId === accountId) ?? null,
    editor: (kind, accountId) => [...editors].find((e) => e.kind === kind && e.accountId === accountId && e.isNew) ?? null,
    hasEditor: () => editors.size > 0,
    waitFor: (pick, ms, signal) => new Promise((resolve, reject) => {
      const done = () => { clearTimeout(timer); listeners.delete(check); signal.removeEventListener("abort", onAbort); };
      const check = () => {
        const v = pick();
        if (v !== null) { done(); resolve(v); }
      };
      const onAbort = () => { done(); reject(new DOMException("aborted", "AbortError")); };
      const timer = setTimeout(() => { done(); reject(new Error("timeout")); }, ms);
      if (signal.aborted) { onAbort(); return; }
      listeners.add(check);
      signal.addEventListener("abort", onAbort);
      check();
    }),
  };
}

const BridgeContext = createContext<AgentBridge | null>(null);

export function AgentBridgeProvider({ bridge, children }: { bridge: AgentBridge; children: ReactNode }) {
  return <BridgeContext.Provider value={bridge}>{children}</BridgeContext.Provider>;
}

/** ReadyMadePanel: its New for `kind` on the page's creator. */
export function useAgentPanel(kind: Kind, accountId: string | null, openNew: () => void) {
  const bridge = useContext(BridgeContext);
  const liveRef = useRef({ kind, accountId, openNew });
  useLayoutEffect(() => { liveRef.current = { kind, accountId, openNew }; });
  const [handle] = useState<PanelHandle>(() => ({
    get kind() { return liveRef.current.kind; },
    get accountId() { return liveRef.current.accountId; },
    openNew: () => liveRef.current.openNew(),
  }));
  useEffect(() => {
    if (!bridge) return;
    return bridge.registerPanel(handle);
  }, [bridge, handle, kind, accountId]);
}

/** How long the agent save waits for its dispatches to render before giving up (nothing saved). */
export const SAVE_WAIT_MS = 1000;

/** ReadyMadeRuleEditor: its state's `dispatch` and its agent save, read live (the latest render's). */
export function useAgentEditor(kind: Kind, live: {
  accountId: string;
  isNew: boolean;
  dispatch: (a: RuleEditorAction) => void;
  /** The editor's save with Enabled forced off. */
  agentSave: () => Promise<SaveResult>;
}) {
  const bridge = useContext(BridgeContext);
  const liveRef = useRef(live);
  // Agent dispatches not rendered yet: `save` waits for them, so it reads the state they made.
  const pending = useRef(0);
  const [waiters] = useState<Array<() => void>>(() => []);
  useLayoutEffect(() => {
    liveRef.current = live;
    pending.current = 0;
    waiters.splice(0).forEach((f) => f());
  });
  const kindRef = useRef(kind);
  useLayoutEffect(() => { kindRef.current = kind; });
  const [handle] = useState<EditorHandle>(() => ({
    get kind() { return kindRef.current; },
    get accountId() { return liveRef.current.accountId; },
    get isNew() { return liveRef.current.isNew; },
    dispatch: (a) => { pending.current += 1; liveRef.current.dispatch(a); },
    save: async () => {
      if (pending.current > 0) {
        await new Promise<void>((res) => { waiters.push(res); setTimeout(res, SAVE_WAIT_MS); });
        if (pending.current > 0) return { ok: false, reason: "The form didn't catch up in time — nothing was saved." };
      }
      return liveRef.current.agentSave();
    },
  }));
  useEffect(() => {
    if (!bridge) return;
    return bridge.registerEditor(handle);
  }, [bridge, handle]);
}
