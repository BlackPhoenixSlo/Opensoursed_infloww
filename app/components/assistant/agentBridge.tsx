"use client";


import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import type { RuleEditorAction } from "@/components/automations/ruleEditorForm";
import type { Kind } from "@/components/compose/payloadRules";
import type { AutoStoriesAction } from "@/components/settings/autoStoriesForm";

export type AgentKind = Kind | "auto_stories";
export type AgentEditorAction = RuleEditorAction | AutoStoriesAction;

export type SaveResult = { ok: true } | { ok: false; reason: string };

export interface PanelHandle {
  readonly kind: Kind;
  readonly accountId: string | null;
  openNew: () => void;
}

export interface EditorHandle {
  readonly kind: AgentKind;
  readonly accountId: string;
  readonly isNew: boolean;
  readonly dirty: boolean;
  dispatch(a: AgentEditorAction): void;
  save: () => Promise<SaveResult>;
}

export interface AgentBridge {
  registerPanel: (h: PanelHandle) => () => void;
  registerEditor: (h: EditorHandle) => () => void;
  panel: (kind: AgentKind, accountId: string) => PanelHandle | null;
  editor: (kind: AgentKind, accountId: string) => EditorHandle | null;
  anyEditor: (kind: AgentKind, accountId: string) => EditorHandle | null;
  hasEditor: () => boolean;
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
    anyEditor: (kind, accountId) => [...editors].find((e) => e.kind === kind && e.accountId === accountId) ?? null,
    hasEditor: () => [...editors].some((e) => e.dirty),
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

export function useAgentPanel(kind: Kind, accountId: string | null, openNew: () => void) {
  const bridge = useContext(BridgeContext);
  const liveRef = useRef({ kind, accountId, openNew });
  useLayoutEffect(() => { liveRef.current = { kind, accountId, openNew }; });
  // One stable handle per mount: StrictMode re-runs register, and the runner must see the same handle.
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

export const SAVE_WAIT_MS = 1000;

export function useAgentEditor<A extends AgentEditorAction>(kind: AgentKind, live: {
  accountId: string;
  isNew: boolean;
  dispatch: (a: A) => void;
  agentSave: () => Promise<SaveResult>;
  ready?: boolean;
  dirty?: boolean;
}) {
  const bridge = useContext(BridgeContext);
  const liveRef = useRef(live);
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
    get dirty() { return liveRef.current.dirty ?? true; },
    dispatch: (a) => { pending.current += 1; liveRef.current.dispatch(a as A); },
    save: async () => {
      if (pending.current > 0) {
        await new Promise<void>((res) => { waiters.push(res); setTimeout(res, SAVE_WAIT_MS); });
        if (pending.current > 0) return { ok: false, reason: "The form didn't catch up in time — nothing was saved." };
      }
      return liveRef.current.agentSave();
    },
  }));
  const ready = live.ready ?? true;
  useEffect(() => {
    if (!bridge || !ready) return;
    return bridge.registerEditor(handle);
  }, [bridge, handle, ready]);
}
