"use client";


import { type FanId } from "@/lib/fanId";
import { useToggleMessageFlag, type MessageFlagSpec } from "@/hooks/useToggleMessageFlag";

const PIN: MessageFlagSpec = {
  field: "isPinned",
  label: "pin",
  path: (id, fanId) => `/api/of/v2/messages/${id}/pin/user/${fanId}`,
  // The rail reads chat-pinned from OF, which knows nothing of the optimistic click and would win over it.
  invalidates: (accountId, fanId) => ["chat-pinned", accountId, String(fanId)],
};

export function useTogglePinMessage(accountId: string | null, fanId: FanId | null) {
  return useToggleMessageFlag(accountId, fanId, PIN);
}
