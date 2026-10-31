"use client";

/**
 * useLikeMessage — toggle a heart-react on a chat message.
 *
 * OF only lets you like the OTHER party's messages (POST on your own
 * returns 404). We hide the affordance for outgoing bubbles in the UI,
 * but the hook still tolerates a 404 by reverting the optimistic flip
 * — failure shouldn't leave the user staring at a wrong-state heart.
 *
 * Optimistic update writes the new `isLiked` flag straight into the
 * ["messages", accountId, fanId] cache so the heart appears instantly.
 */

import { type FanId } from "@/lib/fanId";
import { useToggleMessageFlag, type MessageFlagSpec } from "@/hooks/useToggleMessageFlag";

const LIKE: MessageFlagSpec = {
  field: "isLiked",
  label: "like",
  path: (id) => `/api/of/v2/messages/${id}/like`,
};

export function useLikeMessage(accountId: string | null, fanId: FanId | null) {
  return useToggleMessageFlag(accountId, fanId, LIKE);
}
