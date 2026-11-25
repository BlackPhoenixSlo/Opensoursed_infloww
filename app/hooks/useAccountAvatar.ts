"use client";


import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { REFRESH_KEYS } from "@/lib/screenBundle";

export interface AccountAvatar {
  id?: number | string;
  name?: string | null;
  username?: string | null;
  avatar?: string | null;
  avatarThumbs?: { c50?: string | null; c144?: string | null } | null;
}

export const PROFILE_MAX_AGE_S = 1800;

export async function fetchOwnProfile<T extends { id?: number | string }>(
  accountId: string, signal?: AbortSignal,
): Promise<T | null> {
  try {
    const me = await relay.get<T>("/api/of/v2/users/me",
      { accountId, priority: "background", maxAge: PROFILE_MAX_AGE_S }, signal);
    // Body for another account is null: a row must never show another Creator's face.
    return me?.id != null && String(me.id) === accountId ? me : null;
  } catch {
    return null;
  }
}

export function ofProfileQuery<T extends AccountAvatar = AccountAvatar>(accountId: string | null | undefined) {
  return {
    queryKey: [REFRESH_KEYS.profile, accountId] as const,
    enabled: !!accountId,
    queryFn: ({ signal }: { signal?: AbortSignal }) => fetchOwnProfile<T>(accountId!, signal),
    gcTime: 24 * 60 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  };
}

export function ownAvatar(profile: AccountAvatar | null | undefined, accountId: string | null | undefined) {
  return profile?.id != null && String(profile.id) === accountId ? profile : null;
}

export function useAccountAvatar(accountId: string | null | undefined, fetchEnabled = true) {
  return useQuery<AccountAvatar | null>({
    ...ofProfileQuery(accountId), enabled: !!accountId && fetchEnabled,
    staleTime: (query) => query.state.data && !ownAvatar(query.state.data, accountId) ? 0 : Infinity,
    select: (profile) => ownAvatar(profile, accountId),
  });
}

export function pickAvatarUrl(a: AccountAvatar | null | undefined): string | null {
  if (!a) return null;
  return a.avatarThumbs?.c50 || a.avatarThumbs?.c144 || a.avatar || null;
}
