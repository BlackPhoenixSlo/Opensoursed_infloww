"use client";


import { useMemo } from "react";
import { useQuery, type QueryClient } from "@tanstack/react-query";

import { MASS_PLACEHOLDER_END, MASS_PLACEHOLDER_MIN, orderThread } from "@/hooks/useChatMessages";
import { toUtcIso } from "@/hooks/useInboxRealtime";
import { relay, type OFMessage } from "@/lib/relay";
import { isValidFanId, type FanId } from "@/lib/fanId";
import { SEED_PAGE } from "@/lib/screenBundle";

// Mirrors the relay's cutoff so a stale mass placeholder is not re-seeded on reload.
const SEED_PLACEHOLDER_MAX_AGE_MS = 60 * 60_000;

interface LocalMessageRow {
  account_id: string;
  fan_id: FanId;
  message_id: FanId;
  direction: "in" | "out";
  sender_name: string | null;
  body: string | null;
  media_count: number | null;
  price_cents: number | null;
  is_tip: boolean | null;
  is_paid: boolean | null;
  is_unsent: boolean | null;
  purchased_at: string | null;
  created_at: string | null;
}

interface LocalMessagesResp {
  messages: LocalMessageRow[];
  limit: number;
  next_before_id: FanId | null;
}

// Own key, never ["messages", ...]: two useQuerys on one key race their queryFns and can skip the OF fetch; ChatSurface copies rows across once.
export const seedKey = (accountId: string | null, fanId: FanId | null) =>
  ["messages-local-seed", accountId, fanId] as const;

export function dropSeedMessage(
  qc: QueryClient,
  accountId: string | null,
  fanId: FanId | null,
  messageId: number | string,
): void {
  qc.setQueriesData<LocalMessagesResp>(
    { queryKey: seedKey(accountId, fanId) },
    (curr) => (curr
      // Compared as text: a Fansly message id is a snowflake past 2^53.
      ? { ...curr, messages: curr.messages.filter((r) => String(r.message_id) !== String(messageId)) }
      : curr),
  );
}

export function seedQueryOptions(accountId: string | null, fanId: FanId | null, limit = SEED_PAGE) {
  return {
    queryKey: [...seedKey(accountId, fanId), limit] as const,
    queryFn: () => {
      const qs = new URLSearchParams({ limit: String(limit) });
      return relay.get<LocalMessagesResp>(
        `/admin/messages/${encodeURIComponent(accountId as string)}/${fanId}?${qs.toString()}`,
      );
    },
    staleTime: 5 * 60 * 1000,
  };
}

export function useChatMessagesLocal(opts: {
  enabled?: boolean;
  accountId: string | null;
  fanId: FanId | null;
  limit?: number;
}): { rows: OFMessage[]; isLoading: boolean } {
  const { enabled = true, accountId, fanId, limit = SEED_PAGE } = opts;
  const q = useQuery<LocalMessagesResp>({
    ...seedQueryOptions(accountId, fanId, limit),
    enabled: enabled && !!accountId && fanId != null,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });

  const rows: OFMessage[] = useMemo(
    () => mapRows(q.data?.messages ?? [], accountId, fanId),
    [q.data, accountId, fanId],
  );

  return { rows, isLoading: q.isLoading };
}

// beforeId must be an id OF handed us: synthetic ids (mass 5e15, tips 6e15) sit above real ones and would be re-admitted.
export async function fetchOlderSeed(
  accountId: string | null,
  fanId: FanId | null,
  beforeId: FanId | null,
  limit = 30,
): Promise<OFMessage[]> {
  if (!accountId || fanId == null || !isValidFanId(beforeId)) return [];
  try {
    const qs = new URLSearchParams({ limit: String(limit), before_id: String(beforeId) });
    const resp = await relay.get<LocalMessagesResp>(
      `/admin/messages/${encodeURIComponent(accountId)}/${fanId}?${qs.toString()}`,
    );
    return mapRows(resp.messages ?? [], accountId, fanId);
  } catch {
    return [];
  }
}

export function mergeSeedIntoMessages(
  prev: OFMessage[] | undefined,
  seed: OFMessage[],
): OFMessage[] {
  // Via orderThread, not a prepend: ledger-tip ids (6e15 band) say nothing about time and would stack at the top.
  if (!prev || prev.length === 0) return orderThread(seed);
  const have = new Set(prev.map((m) => String(m.id)));
  const missing = seed.filter((m) => !have.has(String(m.id)));
  return orderThread(missing.length > 0 ? [...missing, ...prev] : prev);
}

export function mapRows(
  raw: LocalMessageRow[],
  accountId: string | null,
  fanId: FanId | null,
  now: number = Date.now(),
): OFMessage[] {
  if (raw.length === 0 || !accountId || fanId == null) return [];
  const ascending = raw.slice().reverse();
  const ownerId: FanId = accountId;
  const out: OFMessage[] = [];
  for (const r of ascending) {
    if (!isValidFanId(r.message_id)) continue;
    if (r.is_unsent) continue;
    // Band-scoped: ids >= MASS_PLACEHOLDER_END are permanent ledger TIP rows; never age them out.
    if (typeof r.message_id === "number" && r.message_id >= MASS_PLACEHOLDER_MIN && r.message_id < MASS_PLACEHOLDER_END) {
      const at = Date.parse(toUtcIso(r.created_at ?? undefined));
      if (!Number.isFinite(at) || now - at > SEED_PLACEHOLDER_MAX_AGE_MS) continue;
    }
    const isOut = r.direction === "out";
    const row: OFMessage & { _side: "left" | "right" } = {
      id: r.message_id,
      text: r.body ?? "",
      fromUser: {
        id: isOut ? ownerId : fanId,
        name: r.sender_name ?? "",
      },
      // The relay's created_at is naive UTC; raw, a non-UTC browser reads it as local time.
      createdAt: r.created_at ? toUtcIso(r.created_at) : new Date().toISOString(),
      media: [],
      mediaCount: r.media_count ?? 0,
      price: (r.price_cents ?? 0) / 100,
      isTip: !!r.is_tip,
      isPaid: !!r.is_paid,
      _side: isOut ? "right" : "left",
    };
    out.push(row);
  }
  return out;
}
