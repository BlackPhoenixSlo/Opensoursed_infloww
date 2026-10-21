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

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { eventBus, type Scope as EventScope } from "@/lib/events";
import { useAccountStateEvents } from "@/hooks/useAccountStateEvents";

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
  useEffect(() => {
    try {
      if (!setBeforeHydrateRef.current) setScopeState(parse(window.localStorage.getItem(LS_KEY)));
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
  }, []);

  const value = useMemo<ScopeContextValue>(() => ({
    scope,
    setScope,
    accountId: scope.kind === "model" ? scope.accountId : null,
    eventScope,
  }), [scope, setScope, eventScope]);

  return (
    <ScopeContext.Provider value={value}>
      <EventOverrideContext.Provider value={setEventScopeOverride}>
        {children}
      </EventOverrideContext.Provider>
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
