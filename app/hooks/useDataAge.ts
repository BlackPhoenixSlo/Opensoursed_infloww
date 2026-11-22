"use client";

/**
 * The I/O shell for components/chat/dataAge's pure decisions
 * (docs/spec/watched-creator-refresher/phase-03-data-age-live-connection-mark.md, Interfaces): each hook is a
 * `useSyncExternalStore` over the tab's Freshness store (hooks/useCreatorFreshness) and the shared clock
 * (lib/ageClock), whose snapshot is the decision itself, kept by identity while what it shows is unchanged, so a
 * tick or another Creator's update re-renders nothing. No fetch: it only reads what the tab already holds.
 */

import { badgeAge, liveMark, type BadgeAge, type LiveMark } from "@/components/chat/dataAge";
import type { BadgeSource } from "@/components/chat/unreadBadge";
import { useFreshnessSelect } from "@/hooks/useCreatorFreshness";
import * as ageClock from "@/lib/ageClock";
import { of } from "@/lib/creatorFreshness";
import type { AccountMeta } from "@/lib/relay";
import { sessionConnectivity } from "@/lib/sessionConnectivity";

const sameMark = (a: LiveMark | null, b: LiveMark | null) =>
  a === b || (!!a && !!b && a.kind === b.kind && a.text === b.text && a.title === b.title);

/** The Creator's No-live-connection / Disconnected mark (null: none), on the Relay's clock. */
export function useLiveMark(
  account: Pick<AccountMeta, "id" | "session_dead_at" | "has_session" | "is_active">,
): LiveMark | null {
  const isDead = !!sessionConnectivity(account)?.dead;
  return useFreshnessSelect(
    (state) => liveMark(of(state, account.id), isDead, Date.now(), ageClock.relayOffset()),
    { same: sameMark, clock: true, server: null },
  );
}

/** What a badge age shows: its render key (a new key re-renders, an unchanged one never does). */
const ageKey = (a: BadgeAge | null) => (a ? `${a.text}\n${a.title}` : null);

/** The Unread chip's "as of" (null: none), on the Relay's clock. `sources`: Phase 2's `unreadBadgeSources` over the
 *  Creators counted from a held total; `dead`: the accounts flagged Dead (`session_dead_at`). */
export function useUnreadBadgeAge(sources: readonly BadgeSource[], dead: ReadonlySet<string>): BadgeAge | null {
  return useFreshnessSelect(
    (state) => badgeAge(sources, state, dead, ageClock.now(), ageClock.relayOffset()),
    { same: (a, b) => ageKey(a) === ageKey(b), clock: true, server: null },
  );
}
