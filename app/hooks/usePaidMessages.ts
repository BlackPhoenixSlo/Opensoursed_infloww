"use client";


import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { reportQuery, type ReportQueryParams } from "@/hooks/reportQuery";
import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface PaidMessageFan {
  username: string | null;
  display_name: string | null;
  avatar_url: string | null;
}

export interface PaidMessageRow {
  account_id: string;
  fan_id: FanId;
  message_id: number;
  fan: PaidMessageFan;
  body: string;
  body_truncated?: boolean;
  media_count: number;
  price_cents: number;
  is_paid: boolean;
  direction?: "in" | "out" | "system";
  is_tip?: boolean;
  sent_at: string | null;
  // May be null even when is_paid (WS pump lag): render "just paid", never fabricate a timestamp.
  purchased_at: string | null;
  sent_by_employee_id: number | null;
  employee_name: string | null;
  sender_name?: string | null;
  automation_kind?: string | null;
  is_mass_summary?: boolean;
  recipient_count?: number;
  viewed_count?: number;
  funnel_name?: string | null;
  mass_run_id?: number | null;
  purchased_count?: number;
  earnings_cents?: number;
  reply_seconds?: number | null;
  is_unsent?: boolean;
  unsent_at?: string | null;
  unsent_reason?: string | null;
}

export interface PaidMessagesPage {
  rows: PaidMessageRow[];
  next_before_id: number | null;
  next_before_sent_at: string | null;
}

export interface PaidMessagesCursor {
  // Keyset (sent_at, message_id) DESC so collapsed mass summaries (synthetic 5e15 ids) interleave by send time.
  sent_at: string | null;
  id: number;
}

export type PaidStatus = "paid" | "unpaid" | "all";
export type MessageType = "paid" | "free" | "all";
export type MessageDirection = "out" | "in" | "any";
export type SenderType = "any" | "employee" | "automation";
export type MessageKind = "all" | "direct" | "mass";

export interface UsePaidMessagesParams extends ReportQueryParams {
  status?: PaidStatus;
  type?: MessageType;
  direction?: MessageDirection;
  fan_id?: FanId | null;
  fan_query?: string | null;
  q?: string | null;
  min_price_cents?: number | null;
  max_price_cents?: number | null;
  unsent_only?: boolean;
  sender_type?: SenderType;
  kind?: MessageKind;
  limit?: number;
}

export function buildPaidMessagesQuery(
  params: UsePaidMessagesParams,
  cursor: PaidMessagesCursor | null = null,
  extra?: { format?: "json" | "csv" },
): string {
  const qs = reportQuery(params);
  if (params.status && params.status !== "all") qs.set("status", params.status);
  if (params.type && params.type !== "paid") qs.set("type", params.type);
  if (params.direction && params.direction !== "out") qs.set("direction", params.direction);
  if (params.fan_id != null) qs.set("fan_id", String(params.fan_id));
  if (params.fan_query && params.fan_query.length >= 2) qs.set("fan_query", params.fan_query);
  if (params.q && params.q.length >= 2) qs.set("q", params.q);
  if (params.min_price_cents != null) qs.set("min_price_cents", String(params.min_price_cents));
  if (params.max_price_cents != null) qs.set("max_price_cents", String(params.max_price_cents));
  if (params.unsent_only) qs.set("unsent_only", "true");
  if (params.sender_type && params.sender_type !== "any") qs.set("sender_type", params.sender_type);
  if (params.kind && params.kind !== "all") qs.set("kind", params.kind);
  if (extra?.format && extra.format !== "json") qs.set("format", extra.format);
  if (extra?.format !== "csv") qs.set("limit", String(params.limit ?? 50));
  if (extra?.format !== "csv" && cursor != null) {
    qs.set("before_id", String(cursor.id));
    if (cursor.sent_at != null) qs.set("before_sent_at", cursor.sent_at);
  }
  return qs.toString();
}

export function usePaidMessages(params: UsePaidMessagesParams) {
  const enabled = !!params.from && !!params.to;

  return useInfiniteQuery<PaidMessagesPage>({
    queryKey: [
      "paid-messages",
      params.from,
      params.to,
      params.account_id ?? null,
      params.employee_id ?? null,
      params.status ?? "all",
      params.type ?? "paid",
      params.direction ?? "out",
      params.fan_id ?? null,
      params.fan_query && params.fan_query.length >= 2 ? params.fan_query : null,
      params.q && params.q.length >= 2 ? params.q : null,
      params.min_price_cents ?? null,
      params.max_price_cents ?? null,
      params.unsent_only ?? false,
      params.sender_type ?? "any",
      params.kind ?? "all",
      params.limit ?? 50,
    ],
    enabled,
    initialPageParam: null as PaidMessagesCursor | null,
    queryFn: ({ pageParam }) =>
      relay.get<PaidMessagesPage>(
        `/admin/paid-messages?${buildPaidMessagesQuery(params, pageParam as PaidMessagesCursor | null)}`,
      ),
    getNextPageParam: (lastPage): PaidMessagesCursor | undefined =>
      lastPage.next_before_id != null
        ? { sent_at: lastPage.next_before_sent_at, id: lastPage.next_before_id }
        : undefined,
    staleTime: 30_000,
    gcTime: 5 * 60 * 1000,
    // Paginated: refetching page 1 after scrolling deep leaves duplicate-row seams.
    refetchOnWindowFocus: false,
    // Memory cap: 1000 rows at limit=50.
    maxPages: 20,
    placeholderData: keepPreviousData,
  });
}
