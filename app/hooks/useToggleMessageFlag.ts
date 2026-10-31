"use client";

/**
 * useToggleMessageFlag — the shared body of useLikeMessage and
 * useTogglePinMessage: flip a boolean on a chat message optimistically in the
 * ["messages", accountId, fanId] cache, POST (on) or DELETE (off) the wire
 * path, and revert the flip if the request fails.
 */

import { useCallback } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";

import { relay, type OFMessage } from "@/lib/relay";
import { isValidFanId, type FanId } from "@/lib/fanId";

export interface MessageFlagSpec {
  /** The OFMessage field the toggle flips. */
  field: "isLiked" | "isPinned";
  /** Console tag on a failed request, e.g. "like". */
  label: string;
  /** The wire path for message `id`; the same path is POSTed and DELETEd. */
  path: (id: string, fanId: FanId) => string;
  /** A query to invalidate once the request succeeded. */
  invalidates?: (accountId: string, fanId: FanId) => QueryKey;
}

export function useToggleMessageFlag(
  accountId: string | null,
  fanId: FanId | null,
  spec: MessageFlagSpec,
) {
  const qc = useQueryClient();
  const { field, label, path, invalidates } = spec;

  const patchLocal = useCallback(
    (messageId: string, value: boolean) => {
      qc.setQueryData<OFMessage[]>(["messages", accountId, fanId], (prev = []) =>
        prev.map((m) => (String(m.id) === messageId ? { ...m, [field]: value } : m)),
      );
    },
    [qc, accountId, fanId, field],
  );

  const toggle = useCallback(
    async (msg: OFMessage) => {
      if (!accountId || fanId == null) return;
      // Exact, not Number(): a Fansly message id is a snowflake past 2^53,
      // so a rounded value here would flip a DIFFERENT message (or 404).
      if (!isValidFanId(msg.id)) return; // optimistic / pseudo bubbles
      const id = String(msg.id);
      const next = !msg[field];
      patchLocal(id, next);
      try {
        const url = path(id, fanId);
        if (next) {
          await relay.post(url, undefined, { accountId });
        } else {
          await relay.delete(url, { accountId });
        }
        if (invalidates) qc.invalidateQueries({ queryKey: invalidates(accountId, fanId) });
      } catch (err) {
        console.warn(`[${label}] failed — reverting`, err);
        patchLocal(id, !next);
      }
    },
    [accountId, fanId, field, label, path, invalidates, patchLocal, qc],
  );

  return { toggle };
}
