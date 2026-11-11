"use client";

/**
 * useAccountAvatar — per-account OF profile avatar fetch for the creator
 * avatars (creator columns, pickers and tabs).
 *
 * Hits `/api/of/v2/users/me` with `X-Account-Id` pinned to the requested
 * account. Shares the dashboard cards' `["of-profile", accountId]` entry
 * (useAccountProfile): one read per Creator serves both. `staleTime:
 * Infinity` here because avatars rarely change and an avatar miss falls back
 * silently to a colored-dot + initial — never user-blocking. The OF call
 * carries `priority: "background"` so it never beats a user-initiated
 * fetch (vault open, chat click) into the relay's per-account lane.
 *
 * Errors swallowed to null so a broken session on one account doesn't
 * cascade into the roster UI. A body whose `id` is not the requested
 * account (OF user id = our account id) is null too: a row never shows
 * another Creator's face (AE: Wren's avatar on all 13 Manage creators rows).
 */

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

/** One Creator's own `/users/me`, or null (failed read, or a body for
 *  anyone else). The queryFn of `["of-profile", accountId]`. */
export async function fetchOwnProfile<T extends { id?: number | string }>(
  accountId: string, signal?: AbortSignal,
): Promise<T | null> {
  try {
    const me = await relay.get<T>("/api/of/v2/users/me", { accountId, priority: "background" }, signal);
    return me?.id != null && String(me.id) === accountId ? me : null;
  } catch {
    return null;
  }
}

/** The `["of-profile", accountId]` read both readers share (this hook and useStats' useAccountProfile): one key,
 *  fetcher, retry and lifetime. Each reader adds its own freshness. */
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

/** Validate cached bodies too: a shared reader may have populated this key. */
export function ownAvatar(profile: AccountAvatar | null | undefined, accountId: string | null | undefined) {
  return profile?.id != null && String(profile.id) === accountId ? profile : null;
}

export function useAccountAvatar(accountId: string | null | undefined, fetchEnabled = true) {
  return useQuery<AccountAvatar | null>({
    ...ofProfileQuery(accountId), enabled: !!accountId && fetchEnabled,
    // A poisoned cache entry must not block the fallback forever.
    staleTime: (query) => query.state.data && !ownAvatar(query.state.data, accountId) ? 0 : Infinity,
    select: (profile) => ownAvatar(profile, accountId),
  });
}

/** Pull the best-available thumbnail URL out of an `AccountAvatar`. Falls
 *  through c50 → c144 → bare `avatar`. Returns null if all empty. */
export function pickAvatarUrl(a: AccountAvatar | null | undefined): string | null {
  if (!a) return null;
  return a.avatarThumbs?.c50 || a.avatarThumbs?.c144 || a.avatar || null;
}
