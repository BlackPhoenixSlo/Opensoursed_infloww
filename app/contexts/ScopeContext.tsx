"use client";


import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { pickOf, resolveWatcherPick, watcherPickReducer, type WatcherPick } from "@/contexts/watcherPickState";
import { eventBus, type Scope as EventScope } from "@/lib/events";
import { useAccountStateEvents } from "@/hooks/useAccountStateEvents";
import { rememberScope } from "@/lib/screenEntry";

const LS_KEY = "chatterly:scope";

export type Scope =
  | { kind: "all" }
  | { kind: "model"; accountId: string };

export interface SetScopeOptions {
  persist?: boolean;
}

interface ScopeContextValue {
  scope: Scope;
  setScope: (s: Scope, options?: SetScopeOptions) => void;
  accountId: string | null;
  eventScope: EventScope;
}

const ScopeContext = createContext<ScopeContextValue | null>(null);
const ScopeHydratedContext = createContext(false);
const EventOverrideContext = createContext<((s: EventScope | null) => void) | null>(null);

function serialize(s: Scope): string {
  return s.kind === "all" ? "all" : `model:${s.accountId}`;
}
function parse(raw: string | null): Scope {
  if (!raw || raw === "all") return { kind: "all" };
  if (raw.startsWith("model:")) {
    const accountId = raw.slice("model:".length);
    if (accountId) return { kind: "model", accountId };
  }
  return { kind: "all" };
}

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const [scope, setScopeState] = useState<Scope>({ kind: "all" });
  const [hydrated, setHydrated] = useState(false);
  // A scope set before hydrate (a Deep link's child effect runs first) wins over the saved one.
  const setBeforeHydrateRef = useRef(false);
  const [eventOverride, setEventScopeOverride] = useState<EventScope | null>(null);
  useAccountStateEvents();

  useEffect(() => {
    try {
      const saved = parse(window.localStorage.getItem(LS_KEY));
      // Cookie mirror: a document load with one Creator saved starts no agency-wide inbox bundle.
      rememberScope(saved.kind === "model");
      if (!setBeforeHydrateRef.current) setScopeState(saved);
    } catch { } finally {
      setHydrated(true);
    }
  }, []);

  const eventScope = eventOverride ?? (serialize(scope) as EventScope);
  useEffect(() => {
    // Never push the initial "all" placeholder before the saved scope is read.
    if (!hydrated) return;
    eventBus.setScope(eventScope);
  }, [eventScope, hydrated]);

  const setScope = useCallback((s: Scope, { persist = true }: SetScopeOptions = {}) => {
    setBeforeHydrateRef.current = true;
    setScopeState(s);
    if (!persist) return;
    try { window.localStorage.setItem(LS_KEY, serialize(s)); } catch {}
    rememberScope(s.kind === "model");
  }, []);

  const value = useMemo<ScopeContextValue>(() => ({
    scope,
    setScope,
    accountId: scope.kind === "model" ? scope.accountId : null,
    eventScope,
  }), [scope, setScope, eventScope]);

  return (
    <ScopeContext.Provider value={value}>
      <ScopeHydratedContext.Provider value={hydrated}>
        <EventOverrideContext.Provider value={setEventScopeOverride}>
          {children}
        </EventOverrideContext.Provider>
      </ScopeHydratedContext.Provider>
    </ScopeContext.Provider>
  );
}

export function useScope(): ScopeContextValue {
  const ctx = useContext(ScopeContext);
  if (!ctx) throw new Error("useScope must be used inside <ScopeProvider>");
  return ctx;
}

export const useScopeHydrated = (): boolean => useContext(ScopeHydratedContext);

export function useEventScopeOverride(scope: EventScope): void {
  const setEventScopeOverride = useContext(EventOverrideContext);
  if (!setEventScopeOverride) throw new Error("useEventScopeOverride must be used inside <ScopeProvider>");
  useEffect(() => {
    setEventScopeOverride(scope);
    return () => setEventScopeOverride(null);
  }, [scope, setEventScopeOverride]);
}

export function ScopeOverride({ accountId, children }: { accountId: string | null; children: React.ReactNode }) {
  const parent = useScope();
  const value = useMemo<ScopeContextValue>(
    () => (accountId ? { ...parent, scope: { kind: "model", accountId }, accountId } : parent),
    [parent, accountId],
  );
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

export function useDropWatcherScope(watcherIds: readonly string[]): void {
  const { scope, setScope } = useScope();
  const stale = scope.kind === "model" && watcherIds.includes(scope.accountId);
  useEffect(() => {
    if (stale) setScope({ kind: "all" });
  }, [stale, setScope]);
}

export const WATCHER_PICK_KEY = "chatterly:ofm-watcher";

function readWatcherPick(): WatcherPick | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(WATCHER_PICK_KEY);
    if (!raw) return null;
    const { id, over } = JSON.parse(raw) as { id?: unknown; over?: unknown };
    return typeof id === "string" && id && typeof over === "string" ? { id, over } : null;
  } catch {
    return null;
  }
}

// A watcher (fan account) pick lives here only, never in the outer scope: that drives SSE, composers and the assistant, none of which may act as a watcher.
export function WatcherScope({ watcherIds, pickable, loaded, children }: {
  watcherIds: readonly string[];
  pickable: readonly string[];
  loaded: boolean;
  children: React.ReactNode;
}) {
  const parent = useScope();
  const hydrated = useContext(ScopeHydratedContext);
  const [{ pick, saved }, dispatch] = useReducer(watcherPickReducer, undefined,
    () => ({ pick: readWatcherPick(), saved: undefined }));
  const outerKey = serialize(parent.scope);
  const { active, next } = resolveWatcherPick(pick, { hydrated, outerKey, pickable, loaded });
  useEffect(() => {
    if (next !== pick) dispatch({ type: "settle", next });
  }, [next, pick]);
  useEffect(() => {
    if (saved === undefined) return;
    try {
      if (saved) window.localStorage.setItem(WATCHER_PICK_KEY, JSON.stringify(saved));
      else window.localStorage.removeItem(WATCHER_PICK_KEY);
    } catch { }
  }, [saved]);
  const parentSet = parent.setScope;
  const setScope = useCallback((s: Scope, options: SetScopeOptions = {}) => {
    const p = pickOf(s, watcherIds, hydrated, outerKey);
    dispatch({ type: "pick", pick: p, persist: options.persist !== false });
    if (!p) parentSet(s, options);
  }, [watcherIds, parentSet, outerKey, hydrated]);
  const value = useMemo<ScopeContextValue>(
    () => (active
      ? { ...parent, scope: { kind: "model", accountId: active }, accountId: active, setScope }
      : { ...parent, setScope }),
    [parent, active, setScope],
  );
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}
