"use client";


import { useCallback } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { dropSeedMessage } from "@/hooks/useChatMessagesLocal";
import { relay, RelayError, type OFMessage } from "@/lib/relay";
import { isValidFanId, type FanId } from "@/lib/fanId";

export interface UnsendQueueInfo {
  id: number;
  sentCount?: number;
  viewedCount?: number;
  canUnsend?: boolean;
  unsendSeconds?: number;
  isCanceled?: boolean;
}

export const NOT_CONFIRMED = "OnlyFans did not confirm the unsend";

interface UnsendResp {
  success?: boolean;
  queue?: UnsendQueueInfo | null;
}

const inFlight = new WeakMap<QueryClient, Map<string, Promise<UnsendResp | null>>>();

export function useUnsendMessage(accountId: string | null, fanId: FanId | null) {
  const qc = useQueryClient();
  const queryKey = ["messages", accountId, fanId] as const;

  const unsendOne = useCallback(
    async (msg: OFMessage): Promise<UnsendResp | null> => {
      if (!accountId || fanId == null) return null;
      if (!isValidFanId(msg.id)) return null;
      // Keep the id exactly as sent: Number() rounds a Fansly snowflake, and on a destructive DELETE that targets another message.
      const id = String(msg.id);
      const out = inFlight.get(qc) ?? new Map<string, Promise<UnsendResp | null>>();
      inFlight.set(qc, out);
      const key = `${accountId}:${id}`;
      const pending = out.get(key);
      if (pending) return pending;
      const call = (async (): Promise<UnsendResp | null> => {
        const prev = qc.getQueryData<OFMessage[]>(queryKey);
        qc.setQueryData<OFMessage[]>(queryKey, (curr = []) =>
          curr.filter((m) => String(m.id) !== id),
        );

        try {
          const resp = await relay.delete<UnsendResp>(
            `/api/of/v2/messages/${id}`,
            { accountId },
            { withUserId: fanId },
          );
          // OF answers {"success": true}; a 2xx without it is a refusal.
          if (resp?.success !== true) throw new Error(NOT_CONFIRMED);
          dropSeedMessage(qc, accountId, fanId, id);
          qc.invalidateQueries({ queryKey: ["msg-attribution", accountId, fanId] });
          return resp;
        } catch (err) {
          const at = prev?.findIndex((m) => String(m.id) === id) ?? -1;
          if (prev && at >= 0) {
            qc.setQueryData<OFMessage[]>(queryKey, (curr = []) => {
              if (curr.some((m) => String(m.id) === id)) return curr;
              const ids = new Set(curr.map((m) => String(m.id)));
              const next = prev.slice(at + 1).find((m) => ids.has(String(m.id)));
              const i = next ? curr.findIndex((m) => String(m.id) === String(next.id)) : curr.length;
              return [...curr.slice(0, i), prev[at], ...curr.slice(i)];
            });
          }
          const reason = err instanceof RelayError ? err.message : String(err);
          console.warn("[unsend] failed — restoring bubble:", reason);
          throw err;
        }
      })().finally(() => out.delete(key));
      out.set(key, call);
      return call;
    },
    [accountId, fanId, qc, queryKey],
  );

  const unsendQueue = useCallback(
    async (queueId: number): Promise<void> => {
      if (!accountId) return;
      if (!Number.isFinite(queueId) || queueId <= 0) return;
      await relay.delete(`/api/of/v2/messages/queue/${queueId}`, { accountId });
    },
    [accountId],
  );

  return { unsendOne, unsendQueue };
}
