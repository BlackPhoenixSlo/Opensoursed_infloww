"use client";


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
