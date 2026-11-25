"use client";


import { badgeAge, liveMark, type BadgeAge, type LiveMark } from "@/components/chat/dataAge";
import type { BadgeSource } from "@/components/chat/unreadBadge";
import { useFreshnessSelect } from "@/hooks/useCreatorFreshness";
import * as ageClock from "@/lib/ageClock";
import { of } from "@/lib/creatorFreshness";
import type { AccountMeta } from "@/lib/relay";
import { sessionConnectivity } from "@/lib/sessionConnectivity";

const sameMark = (a: LiveMark | null, b: LiveMark | null) =>
  a === b || (!!a && !!b && a.kind === b.kind && a.text === b.text && a.title === b.title);

export function useLiveMark(
  account: Pick<AccountMeta, "id" | "session_dead_at" | "has_session" | "is_active">,
): LiveMark | null {
  const isDead = !!sessionConnectivity(account)?.dead;
  return useFreshnessSelect(
    (state) => liveMark(of(state, account.id), isDead, Date.now(), ageClock.relayOffset()),
    { same: sameMark, clock: true, server: null },
  );
}

const ageKey = (a: BadgeAge | null) => (a ? `${a.text}\n${a.title}` : null);

export function useUnreadBadgeAge(sources: readonly BadgeSource[], dead: ReadonlySet<string>): BadgeAge | null {
  return useFreshnessSelect(
    (state) => badgeAge(sources, state, dead, ageClock.now(), ageClock.relayOffset()),
    { same: (a, b) => ageKey(a) === ageKey(b), clock: true, server: null },
  );
}
