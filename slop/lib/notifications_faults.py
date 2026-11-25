from __future__ import annotations

from datetime import timedelta

PAGED = ("notifications: on a frozen feed (nothing filed meanwhile), every session paging GET "
         "/admin/agency-notifications (limit 30/50/100/200, pages spread over --users sessions) gets every row "
         "exactly once, newest first (created_at desc, id desc)")
LATER_UNREAD = "notifications: rows filed after the last read-all answered stay unread"
PRUNED = ("notifications: the sweep (tick at the seed's now) drops every row older than RETENTION "
          "and keeps every younger one, the boundary rows included")
CLICK_SYNC = ("notifications: after the page phase's concurrent clicks (POST /{id}/read, one per session), "
              "each owner SSE stream's last agency_notifications equals SQL unread")
PRUNE_PUSHED = ("notifications: after a sweep that only prunes (files nothing, unread rows among the pruned), "
                "each owner SSE stream's last agency_notifications equals SQL unread")
BADGE = "notifications: the unread count from GET and each owner SSE stream's last agency_notifications equals SQL"
READ_ONE = "notifications: POST /{id}/read marks exactly the rows clicked (SQL unread = seeded unread - clicked)"
DISMISSED = ("notifications: Clear all (POST /dismiss-all from the bell's Agency tab) empties the API list and "
             "leaves no undismissed or unread row in SQL, and a sweep after it files none of the cleared events again "
             "(the dedupe survives the dismiss)")
UI_SETTINGS = ("notifications UI: the bell's Settings tab (beside OnlyFans / Agency) opens the notification settings, "
               "with the Messages, Purchases, Tips and Subscribers toasts and Enabled on, also for a browser that "
               "saved them off before the 2026-11-10 defaults (one-time migration)")
UI_FEED = ("notifications UI: /notifications renders, the bell's badge shows the API unread, its Agency tab "
           "lists the newest rows, and its Mark all read leaves SQL and API unread at 0")

READ_ALL_LAG_S = 2.0


def _read_all_marks_later() -> None:
    import asyncio

    import notifications_api as na

    real = na._mark_read
    pending: set = set()

    async def mark(user_id, notification_id):
        out = await real(user_id, notification_id)
        if notification_id is None:
            async def later():
                await asyncio.sleep(READ_ALL_LAG_S)
                await real(user_id, None)
            t = asyncio.get_running_loop().create_task(later())
            pending.add(t)
            t.add_done_callback(pending.discard)
        return out

    na._mark_read = mark


def _page_skips_offset() -> None:
    import notifications_api as na
    from sqlalchemy.sql import Select

    real = na.select

    class SkipSelect(Select):
        # same SQL shape as Select: share its compile cache
        inherit_cache = True

        def offset(self, n):
            return super().offset(n + 1 if n else n)

    def select(*a, **k):
        q = real(*a, **k)
        if a and a[0] is na.AgencyNotification:
            # Select's generative methods copy via self.__class__: kept down the chain
            q.__class__ = SkipSelect
        return q

    na.select = select


def _prune_ignores_retention() -> None:
    import notifications_api as na

    na.RETENTION = timedelta(days=30)


def _prune_not_pushed() -> None:
    import notifications_api as na

    async def push_unread(agencies) -> None:
        return None

    na.push_unread = push_unread


def _dismiss_deletes() -> None:
    import notifications_api as na
    from sqlalchemy import delete

    real = na._dismiss

    async def dismiss(user_id, notification_id, up_to_id=None):
        if notification_id is not None:
            return await real(user_id, notification_id, up_to_id)
        async with na.get_session() as s:
            q = delete(na.AgencyNotification).where(
                na.AgencyNotification.agency_user_id == user_id, na.AgencyNotification.kind != na.PINNED_KIND)
            if up_to_id is not None:
                q = q.where(na.AgencyNotification.id <= up_to_id)
            await s.execute(q)
            unread = await na._unread(s, user_id)
        na._push(user_id, unread)
        return {"unread": unread}

    na._dismiss = dismiss


def register(Fault) -> dict:
    return {
        "read-all-marks-later-rows": Fault(_read_all_marks_later, (LATER_UNREAD,)),
        "notif-page-skips-offset": Fault(_page_skips_offset, (PAGED,)),
        "notif-prune-ignores-retention": Fault(_prune_ignores_retention, (PRUNED,)),
        "notif-prune-not-pushed": Fault(_prune_not_pushed, (PRUNE_PUSHED,)),
        "notif-dismiss-deletes": Fault(_dismiss_deletes, (DISMISSED,)),
    }
