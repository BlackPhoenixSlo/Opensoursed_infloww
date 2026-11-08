"use client";

/**
 * ScopeContext — current inbox scope: "all models" or a single model.
 *
 * Persists in localStorage so refreshing keeps you in the same view.
 * Drives:
 *   • Which `X-Account-Id` header gets sent on relay calls
 *   • Which SSE scope the EventSource subscribes to (eventBus.setScope)
 *   • Which IndexedDB queries filter (db.chats.where('accountId').equals(...))
 *
 * Phase B's Unified Inbox is built on top of this — switching scope
 * doesn't reload data, it just changes the filter the views apply.
 */

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
  /** `false` changes this window's scope (its lists and the SSE scope) without
   *  writing the saved scope, so other windows keep theirs. A Deep link uses
   *  it. Default `true`: today's behaviour. */
  persist?: boolean;
}

interface ScopeContextValue {
  scope: Scope;
  setScope: (s: Scope, options?: SetScopeOptions) => void;
  /** Convenience: the X-Account-Id header to send (null for "all"). */
  accountId: string | null;
  /** The SSE scope the bus follows: this scope's, unless a page overrides
   *  it (useEventScopeOverride). */
  eventScope: EventScope;
}

const ScopeContext = createContext<ScopeContextValue | null>(null);
/** Private: the saved scope has been read (before it, the scope is a placeholder "all"). */
const ScopeHydratedContext = createContext(false);
/** Private: only useEventScopeOverride sets the override. */
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
  // A scope set before the saved one is read wins over it. A child's mount
  // effect (a Deep link's) runs before this provider's hydrate effect.
  const setBeforeHydrateRef = useRef(false);
  // A page that follows a different SSE scope than this one (e.g. "all")
  // — see useEventScopeOverride.
  const [eventOverride, setEventScopeOverride] = useState<EventScope | null>(null);
  // Account-state SSE events invalidate the queries they cover.
  useAccountStateEvents();

  // Hydrate from localStorage. Same pattern as EmployeeContext —
  // browser-only so we do it in an effect, not lazy state.
  // Whether the saved scope is one Creator is mirrored into a cookie (lib/screenEntry.ts): a document load of Messages Pro
  // with one Creator saved starts no agency-wide inbox bundle (AuthGate, the server's inline boot).
  useEffect(() => {
    try {
      const saved = parse(window.localStorage.getItem(LS_KEY));
      rememberScope(saved.kind === "model");
      if (!setBeforeHydrateRef.current) setScopeState(saved);
    } catch { /* ignore */ } finally {
      setHydrated(true);
    }
  }, []);

  // Push every scope change down to the SSE bus so events get filtered
  // server-side. This is fire-and-forget; the bus tears down + reopens.
  // Gated on `hydrated` so we only push the localStorage-resolved scope,
  // never the initial "all" placeholder before the read lands.
  const eventScope = eventOverride ?? (serialize(scope) as EventScope);
  useEffect(() => {
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

/** While the calling component is mounted, the SSE bus follows `scope`
 *  instead of the inbox scope (which is left untouched); unmount restores
 *  it. The provider stays the single writer of eventBus.setScope. */
export function useEventScopeOverride(scope: EventScope): void {
  const setEventScopeOverride = useContext(EventOverrideContext);
  if (!setEventScopeOverride) throw new Error("useEventScopeOverride must be used inside <ScopeProvider>");
  useEffect(() => {
    setEventScopeOverride(scope);
    return () => setEventScopeOverride(null);
  }, [scope, setEventScopeOverride]);
}

/** Its children see one model (`accountId`) in scope; the saved scope, `setScope` and the SSE scope stay the parent's.
 *  null: the parent's scope as is. My profile in All models shows the first model this way (OfMirrorFrame). */
export function ScopeOverride({ accountId, children }: { accountId: string | null; children: React.ReactNode }) {
  const parent = useScope();
  const value = useMemo<ScopeContextValue>(
    () => (accountId ? { ...parent, scope: { kind: "model", accountId }, accountId } : parent),
    [parent, accountId],
  );
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

/** The app's scope never names a watcher (useDropWatcherScope; OF Manager's own watcher pick is WatcherScope's): a
 *  saved scope from before (a chatter's granted watcher, a Creator flagged as a watcher since) is reset to "all" once
 *  the caller's watchers are read. Matches the watcher list, never "missing from the accounts", so a scope survives a
 *  load. Mounted once, outside every WatcherScope (Providers). */
export function useDropWatcherScope(watcherIds: readonly string[]): void {
  const { scope, setScope } = useScope();
  const stale = scope.kind === "model" && watcherIds.includes(scope.accountId);
  useEffect(() => {
    if (stale) setScope({ kind: "all" });
  }, [stale, setScope]);
}

/** OF Manager's own pick of a watcher account (`chatterly:ofm-watcher`), kept apart from the app's scope: JSON
 *  `{id, over}`, `over` the app's scope (serialized) it was picked over. */
export const WATCHER_PICK_KEY = "chatterly:ofm-watcher";

/** The saved watcher pick, as saved (WatcherScope checks `over`). */
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

/**
 * OF Manager's subtree: a watcher account (a fan account, no Creator) can be picked and browsed here like a Creator,
 * yet never becomes the app's scope. The app's scope drives the SSE scope, Messages Pro, the bell, the assistant and
 * every composer, none of which may act as a watcher; so a watcher pick lives here alone (saved under its own key, so
 * a reload keeps it) and the outer scope, its saved value and the SSE scope stay the last Creator's. Any other pick
 * clears the watcher pick and goes to the outer setScope.
 * The pick holds while the app's scope is the one it was picked over (`over`, checked every render): a Creator picked
 * since anywhere (Messages Pro, the switcher, a Pop-out's `?account=`) ends it, and the saved pick is cleared.
 * `watcherIds`: every watcher of the caller (a pick of one never reaches the outer scope); `pickable`: those OF Manager
 * lists (useOfManagerAccounts: a captured session, active). A pick outside `pickable` is dropped once `loaded`.
 * The rules are `watcherPickState`'s (resolver + reducer); this component only dispatches and saves.
 * Never writes the outer scope with a watcher, so useDropWatcherScope (outer scope only) never fires on its account.
 */
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
    } catch { /* ignore */ }
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
