"use client";

/**
 * useTogglePinMessage — pin/unpin a message inside a chat.
 *
 * OF wire path is /messages/{msg_id}/pin/user/{chat_partner_id}. The
 * partner id is the fan's user id for this chat. Like the like hook,
 * we flip `isPinned` optimistically in the messages cache and revert
 * on failure.
 *
 * Outgoing AND incoming messages can be pinned (unlike `like` which
 * only works on the other party's messages), so we don't gate by
 * sender direction here.
 */

import { type FanId } from "@/lib/fanId";
import { useToggleMessageFlag, type MessageFlagSpec } from "@/hooks/useToggleMessageFlag";

const PIN: MessageFlagSpec = {
  field: "isPinned",
  label: "pin",
  path: (id, fanId) => `/api/of/v2/messages/${id}/pin/user/${fanId}`,
  // The rail reads `chat-pinned` (asked of OF, not filtered out of the
  // loaded backlog), and that query knows nothing about this click. Without
  // this it serves the pre-click set for its whole staleTime AND wins over
  // the optimistic patch, so the pin the operator just made appears to have
  // been ignored.
  invalidates: (accountId, fanId) => ["chat-pinned", accountId, String(fanId)],
};

export function useTogglePinMessage(accountId: string | null, fanId: FanId | null) {
  return useToggleMessageFlag(accountId, fanId, PIN);
}
