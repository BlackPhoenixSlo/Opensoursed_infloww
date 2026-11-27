"use client";


import { useCallback } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { isChatterOnly } from "@/lib/session";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { useScope } from "@/contexts/ScopeContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { usePrincipalId } from "@/hooks/useEmployeeKey";
import { zoneOffsetNow } from "@/lib/creatorClock";
import { browserTimeZone, type WeekStart } from "@/lib/shifts";

export type FeatureFlag = "fansly_manager" | "leak_tracker";
export type FeatureFlags = Record<FeatureFlag, boolean>;

export interface AppliedSettings {
  /** `null` zones mean "use the browser's". `hide_trial_popup`: Settings › Preferences "Disable free trial popup". */
  preferences: { tz: string | null; report_tz: string | null; week_start: WeekStart; hide_trial_popup?: boolean };
  messaging: { ai_translation: boolean };
  permissions: {
    enforced: boolean; pages: string[] | null; scope: "all" | "self"; opt_in?: string[]; denied_actions?: string[];
    denied_cards?: string[];
  };
  flags: FeatureFlags;
  reports?: { creator_cols: string[] | null };
}

export const APPLIED_SETTINGS_KEY = ["applied-settings"] as const;

export function appliedQuery(principalId: string, accountId: string | null) {
  return {
        // principal in the key: a stale tab of the previous login must never write into this login's settings
    queryKey: [...APPLIED_SETTINGS_KEY, principalId, accountId],
    queryFn: () => relay.get<AppliedSettings>("/admin/settings/applied", { accountId }),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  };
}

export function useAppliedSettings() {
  const { accountId } = useScope();
  return useQuery<AppliedSettings>(appliedQuery(usePrincipalId(), accountId));
}

export function useAppliedSettingsAfterMount(enabled: boolean): { settings?: AppliedSettings; failed: boolean; retry: () => void; key: string } {
  const { accountId } = useScope();
  const query = appliedQuery(usePrincipalId(), accountId);
    // a restored snapshot counts fresh for 60 s and another tab may have re-saved a stale one, so decisions need this mount's own read
  const q = useQuery<AppliedSettings>({ ...query, staleTime: 0, enabled });
  const answered = !q.isError && q.isFetchedAfterMount && !q.isPlaceholderData;
  const { refetch } = q;
  const retry = useCallback(() => void refetch(), [refetch]);
  return { settings: answered ? q.data : undefined, failed: q.isError, retry, key: JSON.stringify(query.queryKey) };
}

export function useTranslationAllowed(accountId: string | null): boolean | undefined {
  const chatterOnly = isChatterOnly(useOptionalUser()?.user, useOptionalChatter()?.chatter);
  const q = useQuery<AppliedSettings>({ ...appliedQuery(usePrincipalId(), accountId), enabled: chatterOnly });
  if (!chatterOnly) return true;
  return q.data?.messaging.ai_translation;
}

export function useReportTimeZone(accountId: string | null): string | null {
  return useQuery<AppliedSettings>(appliedQuery(usePrincipalId(), accountId)).data?.preferences?.report_tz ?? null;
}

export function useAgencyTimeZone(): string {
  const stored = useAppliedSettings().data?.preferences?.tz;
  return stored && zoneOffsetNow(stored) ? stored : browserTimeZone();
}

export function useWeekStart(): WeekStart {
  return useAppliedSettings().data?.preferences?.week_start ?? "monday";
}
