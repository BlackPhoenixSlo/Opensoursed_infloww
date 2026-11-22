"use client";

/**
 * useUnsendMessage — delete a chat message via OF's unsend endpoint.
 *
 * Two surfaces:
 *   • `unsendOne(msg)` — DELETE /messages/{id} with `{withUserId: fanId}`.
 *     Removes the bubble from THIS chat only. If OF replies with a
 *     `queue` block (the message was part of a mass send), it's returned
 *     so the caller can offer a follow-up "also unsend from everyone".
 *   • `unsendQueue(queueId)` — DELETE /messages/queue/{id}. Cancels the
 *     entire mass-message queue, which unsends the bubble from EVERY fan
 *     who hasn't already read past OF's 24h edit window.
 *
 * Optimistic: `unsendOne` drops the message from the ["messages", account,
 * fan] cache before the request. On failure we re-insert at the original
 * index so the bubble doesn't silently disappear.
 *
 * On success it also calls `dropSeedMessage` — the DB seed is re-hydrated
 * into the thread on every mount, so a row left standing there paints the
 * unsent bubble straight back (see useChatMessagesLocal).
 *
 * Outside OF's edit window (~24h) the upstream returns 4xx — we revert.
 * A 2xx counts only with OF's `success: true` (of_sends.unsend_message: OF
 * answers `{"success": true}`, plus `queue` for a mass send); anything else
 * (`success: false`, `{}`, no body) throws NOT_CONFIRMED and reverts, so the
 * caller never reads a refusal as "Unsent".
 */

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

/** The error `unsendOne` throws when OF's 2xx is not `success: true`. */
export const NOT_CONFIRMED = "OnlyFans did not confirm the unsend";

interface UnsendResp {
  success?: boolean;
  queue?: UnsendQueueInfo | null;
}

/**
 * The unsends still out, per QueryClient, by `accountId:messageId`. Every caller (the mirror's menu and
 * Unsend PPV, the chat's UnsendChoice, the Messages list's button) shares one DELETE per message: a second
 * confirm while it is out gets the same answer and sends nothing (W30 W3/S1).
 */
const inFlight = new WeakMap<QueryClient, Map<string, Promise<UnsendResp | null>>>();

export function useUnsendMessage(accountId: string | null, fanId: FanId | null) {
  const qc = useQueryClient();
  const queryKey = ["messages", accountId, fanId] as const;

  const unsendOne = useCallback(
    async (msg: OFMessage): Promise<UnsendResp | null> => {
      if (!accountId || fanId == null) return null;
      // The id stays EXACTLY as the wire sent it. `Number(msg.id)` rounded a
      // Fansly snowflake (900715634200489987 -> 900715634200490000) and that
      // rounded value was then the target of a DELETE — at best a silent 404,
      // at worst naming a different real message. A truncated id on a read
      // path is a stale badge; on a destructive call it is data loss.
      if (!isValidFanId(msg.id)) return null;
      const id = String(msg.id);
      const out = inFlight.get(qc) ?? new Map<string, Promise<UnsendResp | null>>();
      inFlight.set(qc, out);
      const key = `${accountId}:${id}`;
      const pending = out.get(key);
      if (pending) return pending;
      const call = (async (): Promise<UnsendResp | null> => {
        // Optimistic: snapshot prior state so we can restore on failure,
        // then drop the bubble from the cache.
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
          if (resp?.success !== true) throw new Error(NOT_CONFIRMED);
          dropSeedMessage(qc, accountId, fanId, id);
          // The relay stamped `unsent_at` on our row: refetch the attribution
          // map so the thread draws "Message withdrawn" where the bubble stood.
          qc.invalidateQueries({ queryKey: ["msg-attribution", accountId, fanId] });
          return resp;
        } catch (err) {
          // Put back only this bubble, before the one that followed it: the
          // whole snapshot would also revive a concurrent unsend that OF took (W30 W4).
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
