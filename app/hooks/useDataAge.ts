"use client";

/**
 * The I/O shell for components/chat/dataAge's pure decisions
 * (docs/spec/watched-creator-refresher/phase-03-data-age-live-connection-mark.md, Interfaces): each hook is a
 * `useSyncExternalStore` over the tab's Freshness store (hooks/useCreatorFreshness) and the shared clock
 * (lib/ageClock), whose snapshot is the decision itself, kept by identity while what it shows is unchanged, so a
 * tick or another Creator's update re-renders nothing. No fetch: it only reads what the tab already holds.
 */

import { useCallback, useRef, useSyncExternalStore } from "react";
import { hashKey, useQueryClient } from "@tanstack/react-query";

import { badgeAge, liveMark, type BadgeAge, type LiveMark } from "@/components/chat/dataAge";
import type { BadgeSource } from "@/components/chat/unreadBadge";
import { creatorFreshnessKey } from "@/hooks/useCreatorFreshness";
import { usePrincipalId } from "@/hooks/useEmployeeKey";
import * as ageClock from "@/lib/ageClock";
import { of, type CreatorFreshnessState } from "@/lib/creatorFreshness";
import type { AccountMeta } from "@/lib/relay";
import { sessionConnectivity } from "@/lib/sessionConnectivity";

const sameMark = (a: LiveMark | null, b: LiveMark | null) =>
  a === b || (!!a && !!b && a.kind === b.kind && a.text === b.text && a.title === b.title);

/** The Creator's No-live-connection / Disconnected mark (null: none), on the Relay's clock. */
export function useLiveMark(
  account: Pick<AccountMeta, "id" | "session_dead_at" | "has_session" | "is_active">,
): LiveMark | null {
  const qc = useQueryClient();
  const queryKey = creatorFreshnessKey(usePrincipalId());
  const hash = hashKey(queryKey);
  const isDead = !!sessionConnectivity(account)?.dead;
  const subscribe = useCallback((onChange: () => void) => {
    const offStore = qc.getQueryCache().subscribe((ev) => { if (ev.query.queryHash === hash) onChange(); });
    const offClock = ageClock.subscribe(onChange);
    return () => { offStore(); offClock(); };
  }, [qc, hash]);
  const last = useRef<LiveMark | null>(null);
  const snapshot = () => {
    const facts = of(qc.getQueryData<CreatorFreshnessState>(queryKey), account.id);
    const next = liveMark(facts, isDead, Date.now(), ageClock.relayOffset());
    if (!sameMark(last.current, next)) last.current = next;
    return last.current;
  };
  return useSyncExternalStore(subscribe, snapshot, () => null);
}

/** What a badge age shows: its render key (a new key re-renders, an unchanged one never does). */
const ageKey = (a: BadgeAge | null) => (a ? `${a.text}\n${a.title}` : null);

/** The Unread chip's "as of" (null: none), on the Relay's clock. `sources`: Phase 2's `unreadBadgeSources` over the
 *  Creators counted from a held total; `dead`: the accounts flagged Dead (`session_dead_at`). */
export function useUnreadBadgeAge(sources: readonly BadgeSource[], dead: ReadonlySet<string>): BadgeAge | null {
  const qc = useQueryClient();
  const queryKey = creatorFreshnessKey(usePrincipalId());
  const hash = hashKey(queryKey);
  const subscribe = useCallback((onChange: () => void) => {
    const offStore = qc.getQueryCache().subscribe((ev) => { if (ev.query.queryHash === hash) onChange(); });
    const offClock = ageClock.subscribe(onChange);
    return () => { offStore(); offClock(); };
  }, [qc, hash]);
  const last = useRef<BadgeAge | null>(null);
  const snapshot = () => {
    const state = qc.getQueryData<CreatorFreshnessState>(queryKey);
    const next = badgeAge(sources, state, dead, ageClock.now(), ageClock.relayOffset());
    if (ageKey(last.current) !== ageKey(next)) last.current = next;
    return last.current;
  };
  return useSyncExternalStore(subscribe, snapshot, () => null);
}
