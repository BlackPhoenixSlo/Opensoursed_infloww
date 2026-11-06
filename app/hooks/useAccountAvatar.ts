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

export interface AccountAvatar {
  id?: number;
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
    return me && String(me.id) === accountId ? me : null;
  } catch {
    return null;
  }
}

export function useAccountAvatar(accountId: string | null | undefined) {
  return useQuery<AccountAvatar | null>({
    queryKey: ["of-profile", accountId] as const,
    enabled: !!accountId,
    queryFn: ({ signal }) => fetchOwnProfile<AccountAvatar>(accountId!, signal),
    staleTime: Infinity,
    gcTime: 24 * 60 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

/** Pull the best-available thumbnail URL out of an `AccountAvatar`. Falls
 *  through c50 → c144 → bare `avatar`. Returns null if all empty. */
export function pickAvatarUrl(a: AccountAvatar | null | undefined): string | null {
  if (!a) return null;
  return a.avatarThumbs?.c50 || a.avatarThumbs?.c144 || a.avatar || null;
}
