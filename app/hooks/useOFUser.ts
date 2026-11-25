"use client";


import { useSyncExternalStore } from "react";
import { useQuery, useQueryClient, type Query, type QueryClient } from "@tanstack/react-query";

import { relay, type OFUserMini } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import type { DiscountFan } from "@/lib/fanDiscount";

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

export interface OFUser extends DiscountFan {
  id?: number;
  name?: string;
  username?: string;
  avatar?: string | null;
  lastSeen?: string | null;
  displayName?: string | null;
  notice?: string | null;
  subscribedOnData?: OFSubscribedOnData;
  listsStates?: OFListState[];
  // Native OF restrict: the fan can type but OF stops messages reaching us; distinct from our DB-only automation skip_list.
  isRestricted?: boolean;
  canRestrict?: boolean;
  canReceiveChatMessage?: boolean;
  [k: string]: unknown;
}

export type OFUserName = Omit<OFUserMini, "isRestricted" | "needsHuman" | "autoRenewOff">
  & { lastSeen?: string | null;
    enrichedAt?: number };

const NAME_FIELDS = [
  "id", "name", "username", "avatar", "customNickname", "displayName", "notice", "lastSeen", "isVerified",
] as const satisfies ReadonlyArray<keyof OFUserName>;

export function ofUserFullKey(accountId: string, fanId: FanId) {
  return [...ofUserNameKey(accountId, fanId), "full"];
}

type Avatars = { avatar?: string | null; avatarThumbs?: { c50?: string; c144?: string } };

export function avatarThumb(u: Avatars): string | null {
  return u.avatarThumbs?.c50 || u.avatarThumbs?.c144 || u.avatar || null;
}

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

export function ofUserNameKey(accountId: string, fanId: FanId) {
  return ["of-user", accountId, fanId];
}

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

export function cachedOFUserQuery<T = OFUserName | null>(accountId: string, fanId: FanId) {
  // The real fetcher, never a stub: an invalidation may run either observer's queryFn, and with none react-query logs errors every render.
  return { ...ofUserNameQuery<T>(accountId, fanId), enabled: false, staleTime: Infinity };
}

export function useOFUserNameMap(): ReadonlyMap<string, OFUserName> {
  const store = nameMapStore(useQueryClient());
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}

interface NameMapStore {
  subscribe: (cb: () => void) => () => void;
  get: () => ReadonlyMap<string, OFUserName>;
}
const nameMapStores = new WeakMap<QueryClient, NameMapStore>();

const isNameKey = (k: readonly unknown[]) => k.length === 3 && k[0] === "of-user";
const nameMapKey = (k: readonly unknown[]) => `${String(k[1])}:${String(k[2])}`;

function nameMapStore(qc: QueryClient): NameMapStore {
  const existing = nameMapStores.get(qc);
  if (existing) return existing;
  const cache = qc.getQueryCache();
  const listeners = new Set<() => void>();
  let snapshot: Map<string, OFUserName> | null = null;
  const changed = new Map<string, Query>();
  let notifyQueued = false;
  cache.subscribe((e) => {
    if (!isNameKey(e.query.queryKey)) return;
    const relevant =
      e.type === "added" || e.type === "removed" ||
      (e.type === "updated" && (e.action.type === "success" || e.action.type === "setState"));
    if (!relevant) return;
    if (snapshot) changed.set(nameMapKey(e.query.queryKey), e.query);
    if (notifyQueued) return;
    notifyQueued = true;
    // Once per microtask: a cache event can fire mid-render of another component, where a listener's setState is a React error.
    queueMicrotask(() => {
      notifyQueued = false;
      listeners.forEach((l) => l());
    });
  });
  const store: NameMapStore = {
    subscribe(cb) {
      listeners.add(cb);
      return () => { listeners.delete(cb); };
    },
    get() {
      if (!snapshot) {
        snapshot = new Map();
        for (const q of cache.findAll({ queryKey: ["of-user"] })) {
          const data = q.state.data as OFUserName | null | undefined;
          if (isNameKey(q.queryKey) && data) snapshot.set(nameMapKey(q.queryKey), data);
        }
      } else if (changed.size) {
        const next = new Map(snapshot);
        for (const [key, q] of changed) {
          const data = q.state.data as OFUserName | null | undefined;
          if (data && cache.get(q.queryHash) === q) next.set(key, data);
          else next.delete(key);
        }
        changed.clear();
        snapshot = next;
      }
      return snapshot;
    },
  };
  nameMapStores.set(qc, store);
  return store;
}

export function useCachedOFUser<T = OFUserName | null>(accountId: string, fanId: FanId): T | undefined {
  return useQuery<T>(cachedOFUserQuery<T>(accountId, fanId)).data;
}

export function useOFUser(accountId: string, fanId: FanId) {
  return useQuery<OFUser>({
    ...ofUserQuery<OFUser>(accountId, fanId),
    enabled: !!accountId && !!fanId,
    refetchOnWindowFocus: true,
    // Don't restore refetchOnMount: it puts a live OF /users/{id} on the user lane at every open. No send path reads this; a stale copy is only late.
    refetchOnMount: (q) => q.state.isInvalidated,
  });
}
