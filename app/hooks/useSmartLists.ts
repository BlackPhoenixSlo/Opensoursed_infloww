"use client";

/**
 * useSmartLists — data layer for Smart Lists (saved dynamic fan segments).
 *
 * Reads/writes smart_lists via the relay's /admin/smart-lists/* routes. A
 * Smart List is a named rules object (`{match, rules[]}`) resolved server-side
 * into a fan-id set — reused as a mass-message audience (include/exclude),
 * previewed live in the builder, and (when active) synced to a real OnlyFans
 * user list by the relay's smart_list_sync worker.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

const KEY = "smart-lists";

export type SmartField =
  // v2 (Infloww's Smart lists conditions)
  | "total_spend" | "ppv_spend" | "tips_spend" | "subscription_spend"
  | "highest_spend" | "last_spend_amount" | "last_purchase_at"
  | "last_message_sent_at" | "sub_start" | "expires_at" | "resubscribed_at"
  | "idle_days"
  | "status" | "renew"
  // v1
  | "lifetime_spend" | "recent_spend" | "last_active_days" | "tag";
export type SmartOp =
  | ">" | ">=" | "<" | "<=" | "==" | "!=" | "between"
  | "within_last" | "more_than" | "within_next"
  | "has" | "not_has";
export type SmartScope = "creator" | "org";
export type SmartTimeframe = "all" | "today" | "yesterday" | "this_week" | "7d" | "30d" | "90d";

export interface SmartRule {
  field: SmartField;
  op: SmartOp;
  value: number | string | [number, number];
  days?: number;               // recent_spend window
  scope?: SmartScope;          // spend + last purchase
  timeframe?: SmartTimeframe;  // spend
}

export interface SmartRules {
  match: "all" | "any";
  rules: SmartRule[];
}

export interface SmartList {
  id: number;
  account_id: string;
  name: string;
  rules: SmartRules;
  created_at: string | null;
  updated_at: string | null;
  // OnlyFans sync (smart_list_sync)
  is_active: boolean;
  of_list_id: number | null;
  sync_state: "syncing" | "ok" | "pending" | "error" | null;
  sync_error: string | null;
  synced_at: string | null;
  member_count: number | null;
}

export interface SmartPreview {
  count: number;
  total_fans: number;
  sample: Array<{
    fan_id: FanId;
    name: string;
    lifetime_spend_cents: number;
    last_active_days: number | null;
    status: string | null;
  }>;
}

interface ListsPage { lists: SmartList[]; max_active: number }

/** One cache entry per account for GET /admin/smart-lists; both hooks read it. */
function listsQuery(accountId: string | null) {
  return {
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
    queryFn: () =>
      relay.get<ListsPage>(`/admin/smart-lists?account_id=${encodeURIComponent(accountId!)}`),
  };
}

const NO_LISTS: SmartList[] = [];

export function useSmartLists(accountId: string | null) {
  return useQuery({
    ...listsQuery(accountId),
    select: (d: ListsPage) => d.lists ?? NO_LISTS,
  });
}

/** The Smart Lists page: the lists plus the active-list quota. Polls while an
 *  active list is syncing or has work left, so its state settles on screen. */
export function useSmartListsPage(accountId: string | null) {
  return useQuery({
    ...listsQuery(accountId),
    refetchInterval: (q) =>
      q.state.data?.lists.some((l) => l.is_active && (l.sync_state == null
        || l.sync_state === "syncing" || l.sync_state === "pending"))
        ? 15_000 : false,
  });
}

export function useCreateSmartList(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<SmartList, Error, { name: string; rules: SmartRules }>({
    mutationFn: (body) =>
      relay.post<SmartList>("/admin/smart-lists", { account_id: accountId, ...body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useUpdateSmartList(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<SmartList, Error, { id: number; name?: string; rules?: SmartRules }>({
    mutationFn: ({ id, ...patch }) =>
      relay.patch<SmartList>(`/admin/smart-lists/${id}`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

/** Delete a list; `deleteOfList` also deletes the OnlyFans list it synced to. */
export function useDeleteSmartList(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { id: number; deleteOfList: boolean }>({
    mutationFn: ({ id, deleteOfList }) =>
      relay.delete(`/admin/smart-lists/${id}${deleteOfList ? "?delete_of_list=true" : ""}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

/** Start (true) or stop (false) syncing a list to an OnlyFans user list. */
export function useSetSmartListActive(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<SmartList, Error, { id: number; active: boolean }>({
    mutationFn: ({ id, active }) =>
      relay.post<SmartList>(`/admin/smart-lists/${id}/${active ? "activate" : "deactivate"}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function usePreviewSmartList(accountId: string | null) {
  return useMutation<SmartPreview, Error, SmartRules>({
    mutationFn: (rules) =>
      relay.post<SmartPreview>("/admin/smart-lists/preview", {
        account_id: accountId, rules,
      }),
  });
}

/** Expand a saved list to its current matching fan-id set — the mass composer
 *  calls this to turn an include/exclude chip into explicit userIds. */
export async function resolveSmartList(id: number): Promise<number[]> {
  const r = await relay.get<{ fan_ids: number[] }>(`/admin/smart-lists/${id}/resolve`);
  return r.fan_ids ?? [];
}
