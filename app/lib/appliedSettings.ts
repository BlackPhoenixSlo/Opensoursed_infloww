"use client";

/**
 * useAppliedSettings — what the Agency's Settings apply to this session, from
 * the Relay's one read `GET /admin/settings/applied` (service/settings_api.py,
 * docs/spec/phase-04-apply-stored-settings.md).
 *
 * Any signed-in session may read it (owner, chatter or Master). The Creator in
 * scope rides along as `X-Account-Id`, which is how a chatter linked to two
 * Agencies names one, so the scope is part of the query key. Every Blob tab
 * save invalidates `APPLIED_SETTINGS_KEY` (settingsBlob.ts), so a change shows
 * with no reload.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { isChatterOnly } from "@/lib/session";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { useScope } from "@/contexts/ScopeContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { zoneOffsetNow } from "@/lib/creatorClock";
import { browserTimeZone, type WeekStart } from "@/lib/shifts";

/** The Agency's feature flags (service/settings_schema.py `FLAGS`, roadmap
 *  8.11): each a page set that ships dark until the Agency turns it on. */
export type FeatureFlag = "fansly_manager";
export type FeatureFlags = Record<FeatureFlag, boolean>;

export interface AppliedSettings {
  /** `null` zones mean "use the browser's". */
  preferences: { tz: string | null; report_tz: string | null; week_start: WeekStart };
  messaging: { ai_translation: boolean };
  /** `pages: null` means every page. `opt_in`: the My Automations pages a
   *  chatter may open (a stored role ticking them, with enforcement on, in
   *  any of its agencies); every one for an owner. `denied_actions`: the `<page>#<action>` Function
   *  permissions (lib/permissionActions.ts) the role denies; none for an owner. `denied_cards`: the `/#card-<id>`
   *  Dashboard cards (lib/dashboardCards.ts) the role hides; none for an owner. */
  permissions: {
    enforced: boolean; pages: string[] | null; scope: "all" | "self"; opt_in?: string[]; denied_actions?: string[];
    denied_cards?: string[];
  };
  /** Every flag the Relay knows, false unless the Agency stored it true. */
  flags: FeatureFlags;
}

/** The query key prefix every Blob tab save invalidates. */
export const APPLIED_SETTINGS_KEY = ["applied-settings"] as const;

/** The read for the Creator `accountId` (null: none in scope). */
function appliedQuery(accountId: string | null) {
  return {
    queryKey: [...APPLIED_SETTINGS_KEY, accountId],
    queryFn: () => relay.get<AppliedSettings>("/admin/settings/applied", { accountId }),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    // A newly picked Creator's read shows the last answer until it lands, so
    // the shell's denied-page gate holds a page only before the first answer.
    placeholderData: keepPreviousData,
  };
}

export function useAppliedSettings() {
  const { accountId } = useScope();
  return useQuery<AppliedSettings>(appliedQuery(accountId));
}

/** Whether this session may use AI translation in a chat with the Creator
 *  `accountId` (spec phase-04, stories 56-59): always for an owner session
 *  (never refused) or no session, else the chatter's Applied
 *  `messaging.ai_translation` for that Creator, `undefined` until that read
 *  answers. The Relay's `/admin/translate` gate reads the same value.
 *  `useEffectiveTranslateMode` (hooks/useTranslateMode.ts) is its one reader
 *  and decides what `undefined` means. */
export function useTranslationAllowed(accountId: string | null): boolean | undefined {
  const chatterOnly = isChatterOnly(useOptionalUser()?.user, useOptionalChatter()?.chatter);
  const q = useQuery<AppliedSettings>({ ...appliedQuery(accountId), enabled: chatterOnly });
  if (!chatterOnly) return true;
  return q.data?.messaging.ai_translation;
}

/** The Agency's report time zone for the Creator `accountId`, as a page that
 *  picks its own Creator reads it; null (the browser's) while loading, on
 *  error and when never saved. */
export function useReportTimeZone(accountId: string | null): string | null {
  return useQuery<AppliedSettings>(appliedQuery(accountId)).data?.preferences?.report_tz ?? null;
}

/** The Agency's time zone (Settings › Preferences "Time zone"), which the
 *  top bar shows and clock records read in: the stored zone while this
 *  browser knows it, else the browser's own (also while loading). */
export function useAgencyTimeZone(): string {
  const stored = useAppliedSettings().data?.preferences?.tz;
  return stored && zoneOffsetNow(stored) ? stored : browserTimeZone();
}

/** The Agency's week start day; Monday while loading, on error and when never
 *  saved (spec phase-04, stories 20 and 22). */
export function useWeekStart(): WeekStart {
  return useAppliedSettings().data?.preferences?.week_start ?? "monday";
}
