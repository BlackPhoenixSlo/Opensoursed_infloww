"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

const KEY = "smart-lists";

export type SmartField =
  | "total_spend" | "ppv_spend" | "tips_spend" | "subscription_spend"
  | "highest_spend" | "last_spend_amount" | "last_purchase_at"
  | "last_message_sent_at" | "sub_start" | "expires_at" | "resubscribed_at"
  | "idle_days"
  | "status" | "renew"
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
  days?: number;
  scope?: SmartScope;
  timeframe?: SmartTimeframe;
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

export function useSmartListsPage(accountId: string | null) {
  return useQuery({
    ...listsQuery(accountId),
    // eslint-disable-next-line local/no-fixed-polling -- stops when the job ends
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

export function useDeleteSmartList(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { id: number; deleteOfList: boolean }>({
    mutationFn: ({ id, deleteOfList }) =>
      relay.delete(`/admin/smart-lists/${id}${deleteOfList ? "?delete_of_list=true" : ""}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

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

export async function resolveSmartList(id: number): Promise<number[]> {
  const r = await relay.get<{ fan_ids: number[] }>(`/admin/smart-lists/${id}/resolve`);
  return r.fan_ids ?? [];
}

export async function resolveSmartLists(ids: ReadonlySet<number>): Promise<number[]> {
  if (ids.size === 0) return [];
  const arrays = await Promise.all([...ids].map((id) => resolveSmartList(id)));
  return Array.from(new Set(arrays.flat()));
}
