"use client";


import { useCallback } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";

import { ifAlert } from "@/components/ui/ifConfirm";
import { errText } from "@/lib/errText";
import { relay, type OFMessage } from "@/lib/relay";
import { isValidFanId, type FanId } from "@/lib/fanId";

export interface MessageFlagSpec {
  field: "isLiked" | "isPinned";
  label: string;
  path: (id: string, fanId: FanId) => string;
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
      if (!isValidFanId(msg.id)) return;
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
        void ifAlert(`Couldn't ${next ? label : `un${label}`}: ${errText(err)}`);
      }
    },
    [accountId, fanId, field, label, path, invalidates, patchLocal, qc],
  );

  return { toggle };
}
