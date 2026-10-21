"use client";

/**
 * useOFUser — single fan's full OF profile, including the `subscribedOnData`
 * block that holds the live spend breakdown + subscription state. Powers
 * the FanDrawer's stats grid (matches what the desktop app shows).
 *
 * 5-minute staleTime, NO refetch-on-mount (except after an invalidation),
 * focus refetch kept. The full profile lives on its own key (`ofUserQuery`),
 * apart from the name key the chat list and name lookups write
 * (`ofUserNameQuery`). Every drawer or actions-menu open used to spend a live
 * OF /users/{id} on the USER lane — the lane reserved for what a click is
 * actually waiting on — for data that barely moves. Now only a Fan's first
 * read (no full profile cached) does: it is what the open waits on, so it
 * stays on the user lane. The freshness that matters here is PUSHED, not
 * polled: inbound
 * money invalidates this key through `invalidateFanRevenue`
 * ([useInboxRealtime.ts]) and the restrict toggle invalidates it directly
 * ([ChatActionsMenu.tsx]). Window focus is the cheap catch-all for a fan
 * changed somewhere else entirely. (Before that it was 3 days, which pinned a
 * stale nickname/note long after OF had changed; 30s + refetch-on-mount fixed
 * the staleness by paying the lane cost on every open.)
 *
 * The one consumer that needs more than this is FanDrawer's EDITABLE
 * nickname/note pair: a stale prefill can be typed over and saved, silently
 * reverting whatever changed the value. The drawer closes that window itself
 * by refetching when the operator ENGAGES an edit affordance — a deliberate
 * click, rare, and the one moment freshness is load-bearing. Don't restore
 * `refetchOnMount` here to serve that case; it would put the per-open cost
 * back on every consumer to protect two fields in one of them.
 *
 * Errors are swallowed by React Query → we surface them through the
 * existing `error` slot, but the drawer keeps showing the DB-derived
 * fields so a flaky OF call doesn't blank the panel.
 */

import { useQuery, type QueryClient } from "@tanstack/react-query";

import { relay, type OFUserMini } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import type { DiscountFan } from "@/lib/fanDiscount";

/** How long a cached read is trusted. Exported because FanDrawer's pre-edit
 *  refresh guards on the SAME window — the risk it closes exists precisely
 *  because reads inside this window are served from cache. */
export const OF_USER_STALE_MS = 5 * 60_000;

export interface OFSubscribedOnData {
  price?: number;
  newPrice?: number;
  regularPrice?: number;
  subscribePrice?: number;
  subscribeAt?: string | null;
  expiredAt?: string | null;
  renewedAt?: string | null;
  status?: string | null;
  isMuted?: boolean;
  unsubscribeReason?: string | null;
  duration?: string | null;
  tipsSumm?: number;
  subscribesSumm?: number;
  messagesSumm?: number;
  postsSumm?: number;
  streamsSumm?: number;
  totalSumm?: number;
  /** OF's personal discount on this Fan's subscription, when one is set
   *  (the Avatar menu's "Special offers ▸"). */
  discountPercent?: number | null;
  discountPeriod?: number | null;
}

export interface OFListState {
  id: string | number;
  type: string;
  name?: string;
  hasUser?: boolean;
  canAddUser?: boolean;
  cannotAddUserReason?: string | null;
}

/** `DiscountFan`: the subscription and block flags the Avatar menu's
 *  "Special offers ▸" reads (OF's `/users/{id}` carries them). */
export interface OFUser extends DiscountFan {
  id?: number;
  name?: string;
  username?: string;
  avatar?: string | null;
  lastSeen?: string | null;
  /** OF's per-subscription rename ("custom name" in their UI) — set
   *  via PUT /subscriptions/{id} `{displayName}`. Empty string means
   *  no rename. */
  displayName?: string | null;
  /** OF's private creator-side note on this fan — set via PUT
   *  /subscriptions/{id} `{notice}`. */
  notice?: string | null;
  subscribedOnData?: OFSubscribedOnData;
  listsStates?: OFListState[];
  /** Native OnlyFans restrict state. A restricted fan can still type, but
   *  OF stops their messages reaching us (`canReceiveChatMessage` flips
   *  false). Toggled via POST/DELETE /users/{id}/restrict. DISTINCT from
   *  our internal "restrict from automations" skip_list (DB-only). */
  isRestricted?: boolean;
  canRestrict?: boolean;
  canReceiveChatMessage?: boolean;
  [k: string]: unknown;
}

/** What the name key holds: the Fan's name, avatar and nicknames, and the
 *  presence and verified mark the full read leaves there. Not the chat row's
 *  relay stamps (restricted, needs a human, auto-renew off): no writer of
 *  the key carries them. */
export type OFUserName = Omit<OFUserMini, "isRestricted" | "needsHuman" | "autoRenewOff">
  & { lastSeen?: string | null };

/** The name key fields a full read refreshes (`OFUserName`'s). */
const NAME_FIELDS = [
  "id", "name", "username", "avatar", "customNickname", "displayName", "notice", "lastSeen", "isVerified",
] as const satisfies ReadonlyArray<keyof OFUserName>;

/** The full profile's key, under the Fan's name key. Money and the restrict,
 *  block and discount toggles invalidate it exactly: the name key holds none
 *  of that, and its observers (the Deep link's, the Group pane's) would
 *  re-read `/users/list` for nothing. Only a manual ↻ invalidates both. */
export function ofUserFullKey(accountId: string, fanId: FanId) {
  return [...ofUserNameKey(accountId, fanId), "full"];
}

/** The avatar fields OF's user objects carry. */
type Avatars = { avatar?: string | null; avatarThumbs?: { c50?: string; c144?: string } };

/** A Fan's avatar as the name key stores it: the thumbnail, not the
 *  full-size image. */
export function avatarThumb(u: Avatars): string | null {
  return u.avatarThumbs?.c50 || u.avatarThumbs?.c144 || u.avatar || null;
}

/** The Fan's FULL OF profile (`/users/{id}`: the money block, subscription,
 *  discount, lists) on its own key (`ofUserFullKey`), with one fetcher, so its
 *  freshness is the full read's own: a name write never re-dates it.
 *
 *  The fetcher also merges the name fields it read into the name key, which
 *  the Thread header's presence line and verified badge, the Fan List and the
 *  Fan tabs read (`lastSeen`, `isVerified`). Shared with any prefetch (on
 *  the background lane). */
export function ofUserQuery<T>(accountId: string, fanId: FanId, priority?: "background") {
  return {
    queryKey: ofUserFullKey(accountId, fanId),
    queryFn: async ({ client }: { client: QueryClient }): Promise<T> => {
      const u = await relay.get<T>(`/api/of/v2/users/${fanId}`, { accountId, priority });
      if (u && typeof u === "object") {
        const read = u as Partial<OFUserName> & Avatars;
        const names: Partial<OFUserName> = {};
        const take = <K extends keyof OFUserName>(k: K) => { if (k in read) names[k] = read[k]; };
        for (const k of NAME_FIELDS) take(k);
        if ("avatar" in read || "avatarThumbs" in read) names.avatar = avatarThumb(read);
        mergeOFUserName(client, accountId, fanId, names);
      }
      return u;
    },
    staleTime: OF_USER_STALE_MS,
  };
}

interface UserListResp { [id: string]: OFUserMini & {
  avatarThumbs?: { c50?: string; c144?: string };
} }

/** The Fan's name key `["of-user", aid, fid]`: name, avatar, nicknames, and
 *  whatever the full read merged in. Its one fetcher is the slim `/users/list`
 *  lookup (the Deep link's and the Group pane's), written over what is cached
 *  so `lastSeen` stays. Every other write goes through `mergeOFUserName`. */
export function ofUserNameKey(accountId: string, fanId: FanId) {
  return ["of-user", accountId, fanId];
}

/** The name key's one writer outside its fetcher: `fields` merged over what
 *  is cached (or a function of it, to keep a cached nickname); a first write
 *  onto an empty key gets the Fan's `id`. Its writers: the full read, the
 *  chat list's enrichment, a nickname save (`useFan`), a notification's
 *  name. */
export function mergeOFUserName(
  qc: QueryClient,
  accountId: string,
  fanId: FanId,
  fields: Partial<OFUserName> | ((prev: OFUserName | null | undefined) => Partial<OFUserName>),
) {
  qc.setQueryData<OFUserName | null>(ofUserNameKey(accountId, fanId), (prev) => ({
    id: fanId,
    ...prev,
    ...(typeof fields === "function" ? fields(prev) : fields),
  }));
}

/** The name key with its fetcher (`ofUserNameKey`). */
export function ofUserNameQuery<T = OFUserName | null>(accountId: string, fanId: FanId) {
  const queryKey = ofUserNameKey(accountId, fanId);
  return {
    queryKey,
    queryFn: async ({ client }: { client: QueryClient }): Promise<T> => {
      const resp = await relay.get<UserListResp>(`/api/of/v2/users/list?ids=${fanId}&view=m`, { accountId });
      const prev = client.getQueryData<Record<string, unknown>>(queryKey);
      const u = resp?.[String(fanId)];
      if (!u) return (prev ?? null) as T;
      return {
        ...prev,
        id: fanId,
        name: u.name,
        username: u.username,
        avatar: avatarThumb(u),
        customNickname: u.customNickname ?? null,
        displayName: u.displayName ?? null,
        notice: u.notice ?? null,
      } as T;
    },
    staleTime: OF_USER_STALE_MS,
  };
}

/** The name key observed, with no request of its own (`enabled: false`).
 *  Its `queryFn` is the key's real fetcher, never a stub: when the key is
 *  invalidated while an active observer shares it, either observer's fetcher
 *  may run the refetch (a throwing stub would end it in an error), and with
 *  none at all react-query logs "No queryFn was passed" on every render in
 *  development (ticket 95: those console errors failed `scripts/ui-shots.sh`). */
export function cachedOFUserQuery<T = OFUserName | null>(accountId: string, fanId: FanId) {
  return { ...ofUserNameQuery<T>(accountId, fanId), enabled: false, staleTime: Infinity };
}

/** The Fan's name key as the cache holds it: the Thread's header name and the
 *  Chat header's presence line read it. */
export function useCachedOFUser<T = OFUserName | null>(accountId: string, fanId: FanId): T | undefined {
  return useQuery<T>(cachedOFUserQuery<T>(accountId, fanId)).data;
}

export function useOFUser(accountId: string, fanId: FanId) {
  return useQuery<OFUser>({
    ...ofUserQuery<OFUser>(accountId, fanId),
    enabled: !!accountId && !!fanId,
    // Policy + its invalidation sources are documented in the header above.
    // Also persisted across reloads ([providers.tsx] PERSIST_PREFIXES
    // "of-user"), so the 5 minutes survive a refresh.
    //
    // Audited before relaxing: no send path reads this. The drawer renders
    // subscribedOnData.price as a display Stat, and isRestricted is ORed
    // with the chat row + the local registry, so a stale copy can only be
    // late, never authoritative. The exception — the drawer's editable
    // nickname/note — is handled at the edit site, not here.
    refetchOnWindowFocus: true,
    // A money or toggle invalidation that landed with no reader mounted (the
    // drawer and the avatar menu closed) is read on the next open.
    refetchOnMount: (q) => q.state.isInvalidated,
  });
}
