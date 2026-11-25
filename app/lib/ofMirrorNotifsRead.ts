"use client";

import { useMarkNotifsReadOnce } from "@/hooks/useOfNotifCount";
import { mirrorQuery } from "@/lib/ofMirrorDataQueries";
import { NOTIFICATION_COUNTS } from "@/lib/ofMirrorFeedsNotifications";

export const NOTIFS_ALL_PAGE = "notifications/index";

export function useMarkNotifsReadOnOpen(accountId: string | null, page: string, list: { isSuccess: boolean }) {
  useMarkNotifsReadOnce(accountId, page === NOTIFS_ALL_PAGE && list.isSuccess,
    mirrorQuery(accountId, NOTIFICATION_COUNTS, true).queryKey);
}
