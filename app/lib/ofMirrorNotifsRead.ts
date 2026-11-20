"use client";

import { useMarkNotifsReadOnce } from "@/hooks/useOfNotifCount";
import { mirrorQuery } from "@/lib/ofMirrorDataQueries";
import { NOTIFICATION_COUNTS } from "@/lib/ofMirrorFeedsNotifications";

/** The notifications page's All tab, the one whose open OF web answers with its mark-read. */
export const NOTIFS_ALL_PAGE = "notifications/index";

/**
 * OF's mark-read on the notifications page: OF web sends `POST /users/notifications/read` when its All tab opens, so
 * the mirror does too (`useMarkOfNotifsRead`, which also lowers the shared badge count). One write per page open per
 * model, once the tab's list has loaded (a failed list marks nothing), via `useMarkNotifsReadOnce`; a write that went
 * through re-reads the page's own tab counts.
 */
export function useMarkNotifsReadOnOpen(accountId: string | null, page: string, list: { isSuccess: boolean }) {
  useMarkNotifsReadOnce(accountId, page === NOTIFS_ALL_PAGE && list.isSuccess,
    mirrorQuery(accountId, NOTIFICATION_COUNTS, true).queryKey);
}
