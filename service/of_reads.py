from __future__ import annotations

from typing import Any

import badge_watch

# OF marks a chat read on any first-page GET without an `id` cursor; Int64 max returns the newest page and leaves it unread.
PEEK_CURSOR = 9223372036854775807


class ReadsMixin:


    def me(self) -> dict:
        return self.get_json(f"{API_BASE}/users/me")

    def list_chats(self, *, limit: int = 10, order: str = "recent",
                   offset: int = 0, filter: str | None = None,
                   list_id: int | str | None = None,
                   query: str | None = None,
                   skip_users: str | None = "all") -> dict:
        # Search param is `query=`: `search=` is rejected with "Invalid filter". skip_users="all" strips subscribedOn/By from withUser, so peer creators cannot be classified; None omits it.
        params: dict[str, Any] = {
            "limit": limit, "order": order, "offset": offset,
        }
        if skip_users is not None:
            params["skip_users"] = skip_users
        if filter:
            params["filter"] = filter
        if list_id is not None:
            params["list_id"] = list_id
        if query:
            params["query"] = query
        return self.get_json(f"{API_BASE}/chats", params=params)

    def chat_folders(self, *, limit: int = 10, offset: int = 0,
                     filter: str = "can_pin_chat") -> dict:
        params: dict[str, Any] = {
            "filter": filter, "isChat": "true", "skip_users": "all",
            "format": "infinite", "limit": limit, "offset": offset,
        }
        return self.get_json(f"{API_BASE}/lists", params=params)

    def get_messages(self, chat_id: str | int, *, limit: int = 10,
                     order: str = "desc", before_id: str | int | None = None,
                     offset: int | None = None, peek: bool = False) -> dict:
        # OF ignores `limit` and returns fewer (desc 50->34): always loop on hasMore. `id` is an upper bound in both orders.
        if peek and order != "desc":
            raise ValueError("peek requires descending order")
        params: dict[str, Any] = {"limit": limit, "order": order, "skip_users": "all"}
        if before_id is not None:
            params["id"] = before_id
        elif peek and offset is None and order == "desc":
            params["id"] = PEEK_CURSOR
        if offset is not None:
            params["offset"] = offset
        out = self.get_json(f"{API_BASE}/chats/{chat_id}/messages", params=params)
        if "id" not in params and offset is None:
            badge_watch.note_unpeeked(getattr(self, "account_id", None), chat_id)
        return out


    def get_user(self, user_id_or_username: str | int) -> dict:
        return self.get_json(f"{API_BASE}/users/{user_id_or_username}")

    def list_users(self, user_ids: list[str | int], *, view: str = "m") -> dict:
        if not user_ids:
            return {}
        if view not in ("m", "x"):
            raise ValueError(f"view must be 'm' or 'x', got {view!r}")
        from urllib.parse import urlencode
        qs = urlencode([(f"{view}[]", str(uid)) for uid in user_ids])
        return self.get_json(f"{API_BASE}/users/list?{qs}")


    def notifications(self, *, limit: int = 10, offset: int = 0,
                      type: str | None = None, related_user: int | None = None) -> dict:
        # Path is /users/notifications; `type` filters are past-tense singular (subscribed, tipped); plurals 400, untyped is flooded by moderation events.
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if type: params["type"] = type
        if related_user is not None: params["related_user"] = related_user
        return self.get_json(f"{API_BASE}/users/notifications", params=params)

    def notifications_count(self) -> dict:
        return self.get_json(f"{API_BASE}/users/notifications/count")

    def release_form_mentions(self, *, limit: int = 10, offset: int = 0) -> dict:
        return self.get_json(f"{API_BASE}/release-forms/mentions",
                             params={"limit": limit, "offset": offset,
                                     "skip_users": "all", "format": "infinite"})

    def my_settings(self) -> dict:
        return self.get_json(f"{API_BASE}/users/me/settings")

    def user_streams(self, user_id: str | int, *, limit: int = 8, offset: int = 0) -> dict:
        return self.get_json(f"{API_BASE}/users/{user_id}/streams",
                             params={"limit": limit, "offset": offset, "skip_users": "all"})

    def _payout_list_params(self, limit, offset, start, end, marker) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if start: params["startDate"] = start
        if end: params["endDate"] = end
        if marker: params["marker"] = marker
        return params

    def payout_requests(self, *, limit: int = 10, offset: int = 0, start: str | None = None,
                        end: str | None = None, marker: str | None = None) -> dict:
        return self.get_json(f"{API_BASE}/payouts/requests",
                             params=self._payout_list_params(limit, offset, start, end, marker))

    def subscription_counts_all(self) -> dict:
        return self.get_json(f"{API_BASE}/subscriptions/count/all")

    def subscribers_chart(self, *, start: str | None = None, end: str | None = None,
                          by: str | None = None) -> dict:
        params = self._date_range_params(start, end)
        if by: params["by"] = by
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/chart", params=params)

    def vault_media_processing(self) -> dict:
        return self.get_json(f"{API_BASE}/vault/media/processing")

    def labels(self) -> list:
        return self.get_json(f"{API_BASE}/labels")


    def search_users(self, query: str, *, limit: int = 10, offset: int = 0) -> list:
        return self.get_json(f"{API_BASE}/users", params={
            "limit": limit, "offset": offset, "query": query, "view": "se"})

    def performers_search(self, query: str, *, limit: int = 10, offset: int = 0) -> list:
        return self.get_json(f"{API_BASE}/users/performers-search",
                             params={"limit": limit, "offset": offset, "query": query})

    def search_posts(self, query: str, *, limit: int = 10) -> Any:
        return self.get_json(f"{API_BASE}/posts", params={
            "limit": limit, "query": query, "skip_users": "all", "format": "infinite"})

    def release_forms(self, *, limit: int = 20, offset: int = 0, filter: str = "all",
                      sort: str = "date:desc", name: str | None = None) -> Any:
        params: dict[str, Any] = {"limit": limit, "offset": offset, "filter": filter, "sort": sort}
        if name:
            params["name"] = name
        return self.get_json(f"{API_BASE}/release-forms", params=params)

    def tagged_friend_users(
        self, *,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
        filter: str = "all",
        sort: str = "date:desc",
        skip_users: str = "all",
    ) -> Any:
        # Search is `name=` (OF rejects `search=`); response is {items, hasMore}, not {list, hasMore}.
        params: dict[str, Any] = {
            "limit": int(limit),
            "offset": int(offset),
            "skip_users": skip_users,
            "filter": filter,
            "sort": sort,
        }
        if search:
            params["name"] = search[:100]
        return self.get_json(f"{API_BASE}/posts/tagged-friend-users", params=params)

    def user_posts(self, user_id: str | int, *, limit: int = 10,
                   skip_users: str = "all", type: str | None = None,
                   before_publish_time: str | None = None,
                   order: str = "publish_date_desc",
                   format: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit, "skip_users": skip_users}
        if type: params["type"] = type
        if order: params["order"] = order
        if format: params["format"] = format
        if before_publish_time: params["beforePublishTime"] = before_publish_time
        return self.get_json(f"{API_BASE}/users/{user_id}/posts", params=params)


    def subscribers(self, *, type: str = "active", limit: int = 10, offset: int = 0,
                    sort: str = "-users.last_activity", filter: str | None = None,
                    online: bool | None = None, min_spent: int | None = None,
                    min_tips: int | None = None) -> dict:
        params: dict[str, Any] = {"type": type, "limit": limit, "offset": offset, "sort": sort}
        if filter:
            params["filter"] = filter
        if online is not None:
            params["filter[online]"] = 1 if online else 0
        if min_spent is not None:
            params["filter[total_spent]"] = int(min_spent)
        if min_tips is not None:
            params["filter[tips]"] = int(min_tips)
        return self.get_json(f"{API_BASE}/subscriptions/subscribers", params=params)

    def following(self, *, type: str = "active", limit: int = 10, offset: int = 0,
                  format: str | None = "infinite") -> dict:
        params: dict[str, Any] = {"type": type, "limit": limit, "offset": offset}
        if format:
            params["format"] = format
        return self.get_json(f"{API_BASE}/subscriptions/subscribes", params=params)

    def iter_online_subscribers(self, *, type: str = "active", page_size: int = 20,
                                max_fans: int = 1000) -> list[dict]:
        out: list[dict] = []
        seen: set[int] = set()
        offset = 0
        page_size = max(1, min(int(page_size), 20))
        # No-progress guard: some OF list endpoints ignore `offset` and report hasMore forever; stop on a page with nothing new.
        while len(out) < max_fans:
            page = self.subscribers(type=type, limit=page_size, offset=offset, online=True)
            rows = page.get("list", page) if isinstance(page, dict) else page
            if not rows:
                break
            added = 0
            for f in rows:
                fid = f.get("id")
                if fid is None or int(fid) in seen:
                    continue
                seen.add(int(fid))
                out.append(f)
                added += 1
            if added == 0:
                break
            if isinstance(page, dict) and not page.get("hasMore"):
                break
            offset += len(rows)
        return out[:max_fans]

    def unread_chat_fan_ids(self, *, max_fans: int = 100, page_size: int = 20) -> list[int]:
        out: list[int] = []
        seen: set[int] = set()
        offset = 0
        page_size = max(1, min(int(page_size), 50))
        while len(out) < max_fans:
            page = self.list_chats(limit=page_size, offset=offset, filter="unread")
            rows = page.get("list", page) if isinstance(page, dict) else page
            if not rows:
                break
            added = 0
            for ch in rows:
                fid = (ch.get("withUser") or {}).get("id")
                if fid and int(fid) not in seen:
                    seen.add(int(fid))
                    out.append(int(fid))
                    added += 1
            # Same guard: OF ignores `offset` here, so a repeated page must end the loop.
            if added == 0:
                break
            if isinstance(page, dict) and not page.get("hasMore"):
                break
            offset += len(rows)
        return out[:max_fans]


    def list_posts(self, *, limit: int = 10, offset: int = 0,
                   order: str = "publish_date_desc",
                   skip_users: str = "all") -> dict:
        return self.get_json(
            f"{API_BASE}/posts",
            params={"limit": limit, "offset": offset, "order": order, "skip_users": skip_users},
        )

    def get_post(self, post_id: int | str) -> dict:
        return self.get_json(f"{API_BASE}/posts/{post_id}")

    def post_comments(self, post_id: int | str, *, limit: int = 20, offset: int = 0,
                      order: str = "publish_date_desc") -> dict:
        return self.get_json(
            f"{API_BASE}/posts/{post_id}/comments",
            params={"limit": limit, "offset": offset, "order": order},
        )


    def vault_media(self, *, limit: int = 24, offset: int = 0,
                    type: str = "all", list_id: int | None = None,
                    sort: str = "desc", field: str = "recent",
                    query: str | None = None,
                    before_publish_date: str | None = None) -> dict:
        # OF uses `?type=` not `?filter=` (silently ignored); `list` param, not `list_id`.
        params: dict[str, Any] = {
            "limit": limit, "offset": offset, "sort": sort, "field": field,
            "list": str(list_id) if list_id is not None else "all",
        }
        if type and type != "all":
            params["type"] = type
        if query and query.strip():
            params["query"] = query.strip()
        if before_publish_date:
            params["beforePublishDate"] = before_publish_date
        return self.get_json(f"{API_BASE}/vault/media", params=params)

    def vault_media_by_id(self, media_id: int) -> dict:
        # No batch form: `?ids[]=` is silently ignored and returns the default page, so one id per call.
        return self.get_json(f"{API_BASE}/vault/media/{int(media_id)}")

    def vault_lists(self, *, view: str = "main", limit: int = 10, offset: int = 0,
                    query: str | None = None) -> dict:
        # `view=main` is mandatory; any other value 400s "Bad view param".
        params: dict[str, Any] = {"view": view, "limit": limit, "offset": offset}
        if query and query.strip():
            params["query"] = query.strip()
        return self.get_json(f"{API_BASE}/vault/lists", params=params)


    def payout_balances(self) -> dict:
        return self.get_json(f"{API_BASE}/payouts/balances")

    def payout_check_receive(self) -> dict:
        return self.get_json(f"{API_BASE}/payouts/check-receive")


    def settings_story(self) -> dict:
        return self.get_json(f"{API_BASE}/users/settings/story")


    def schedules(self, *, publish_date: str | None = None,
                  publish_date_end: str | None = None,
                  time_zone: str = "Europe/Ljubljana",
                  limit: int = 20) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if publish_date:     params["filter[publishDate]"] = publish_date
        if publish_date_end: params["filter[publishDateEnd]"] = publish_date_end
        params["filter[timeZone]"] = time_zone
        return self.get_json(f"{API_BASE}/schedules", params=params)

    def schedules_later_chat(self, *, limit: int = 10) -> dict:
        return self.get_json(f"{API_BASE}/schedules/later/chat", params={"limit": limit})

    def schedules_later_post(self, *, limit: int = 10, offset: int = 0) -> dict:
        return self.get_json(f"{API_BASE}/schedules/later/post",
                             params={"limit": limit, "offset": offset})


    def get_lists(self, *, limit: int = 20, offset: int = 0) -> dict:
        return self.get_json(
            f"{API_BASE}/lists",
            params={"limit": limit, "offset": offset, "format": "infinite"},
        )

    def get_list(self, list_id: int | str) -> dict:
        return self.get_json(f"{API_BASE}/lists/{list_id}")

    def list_users_in(self, list_id: int | str, *, limit: int = 20, offset: int = 0, query: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if query:
            params["query"] = query
        return self.get_json(f"{API_BASE}/lists/{list_id}/users", params=params)

    def list_posts_in(self, list_id: int | str, *, limit: int = 10, offset: int = 0, type: str | None = None) -> dict:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if type:
            params["type"] = type
        params["skip_users"] = "all"
        return self.get_json(f"{API_BASE}/lists/{list_id}/posts", params=params)


    def transactions(self, *, limit: int = 20, offset: int = 0,
                     type: str | None = None,
                     start: str | None = None, end: str | None = None,
                     start_date: str | None = None, marker: int | str | None = None,
                     tips_source: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if type:  params["type"] = type
        if start: params["start"] = start
        if end:   params["end"] = end
        if start_date: params["startDate"] = start_date
        if marker is not None: params["marker"] = marker
        if tips_source: params["tipsSource"] = tips_source
        return self.get_json(f"{API_BASE}/payouts/transactions", params=params)

    def earning_stats(self, *, by: str = "day",
                      start_date: str | None = None, end_date: str | None = None) -> dict:
        params: dict[str, Any] = {"by": by}
        if start_date: params["startDate"] = start_date
        if end_date:   params["endDate"] = end_date
        return self.get_json(f"{API_BASE}/payouts/stats", params=params)


    def user_stories(self, user_id: str | int) -> dict:
        return self.get_json(f"{API_BASE}/users/{user_id}/stories")

    def user_highlights(self, user_id: str | int) -> dict:
        return self.get_json(f"{API_BASE}/users/{user_id}/stories/highlights")

    def highlight(self, highlight_id: int) -> dict:
        return self.get_json(f"{API_BASE}/stories/highlights/{int(highlight_id)}")

    def user_photos(self, user_id: str | int, *, limit: int = 10, offset: int = 0) -> list:
        return self.get_json(f"{API_BASE}/users/{user_id}/posts/photos",
                             params={"limit": limit, "offset": offset})

    def user_videos(self, user_id: str | int, *, limit: int = 10, offset: int = 0) -> list:
        return self.get_json(f"{API_BASE}/users/{user_id}/posts/videos",
                             params={"limit": limit, "offset": offset})


    def promotions(self, *, offset: int = 0, limit: int = 100) -> dict:
        # Paginated: default page is 10 and hasMore stays true past offset 180; a short walk makes an older live promo look absent.
        return self.get_json(f"{API_BASE}/promotions",
                             params={"offset": int(offset), "limit": int(limit)})


    def get_chat(self, chat_id: str | int) -> dict:
        return self.get_json(f"{API_BASE}/chats/{chat_id}")

    def scheduled_messages(self, *, limit: int = 10, offset: int = 0) -> dict:
        return self.get_json(
            f"{API_BASE}/messages/queue",
            params={"limit": limit, "offset": offset},
        )

    def queued_message(self, queue_id: int) -> dict:
        return self.get_json(f"{API_BASE}/messages/queue/{queue_id}",
                             params={"format": "scheduled"})

    def mass_message_history(self, *, start_date: str, end_date: str,
                             limit: int = 50, offset: int = 0) -> dict:
        return self.engagement_messages("group", start_date=start_date, end_date=end_date,
                                        limit=limit, offset=offset)

    def engagement_messages(self, type: str, *, start_date: str, end_date: str,
                            limit: int = 50, offset: int = 0,
                            query: str | None = None) -> dict:
        params: dict[str, Any] = {"startDate": start_date, "endDate": end_date,
                                  "limit": limit, "offset": offset}
        if query:
            params["query"] = query
        return self.get_json(f"{API_BASE}/users/me/stats/messages/{type}", params=params)

    def get_pinned_messages(self, chat_id: str | int, *, limit: int = 50) -> list[dict]:
        # `filter=pinned` is the only form OF honours (`pinned=1` is silently ignored); hasMore lies on this filter, so the list is returned.
        payload = self.get_json(
            f"{API_BASE}/chats/{chat_id}/messages",
            params={"limit": limit, "order": "desc", "skip_users": "all",
                    "filter": "pinned", "id": PEEK_CURSOR},
        )
        return (payload or {}).get("list") or []

    def chat_media(
        self,
        chat_id: str | int,
        *,
        limit: int = 20,
        offset: int = 0,
        last_id: str | int | None = None,
        skip_users: str | None = None,
        opened: int | None = None,
        purchased: int | None = None,
        from_user: str | int | None = None,
        kind: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if offset:
            params["offset"] = offset
        if last_id is not None:
            params["last_id"] = last_id
        if skip_users is not None:
            params["skip_users"] = skip_users
        if opened is not None:
            params["opened"] = opened
        if purchased is not None:
            params["purchased"] = purchased
        if from_user is not None:
            params["from_user"] = from_user
        if kind is not None and kind not in CHAT_MEDIA_KINDS:
            raise ValueError(f"chat media kind must be one of {CHAT_MEDIA_KINDS}, not {kind!r}")
        segment = f"/{kind}" if kind else ""
        return self.get_json(f"{API_BASE}/chats/{chat_id}/media{segment}", params=params)

    def search_chat(self, chat_id: str | int, query: str, filter: str | None = None) -> list:
        # Param is `query`, not `text` (silently rejected).
        params: dict[str, Any] = {"query": query}
        if filter: params["filter"] = filter
        return self.get_json(f"{API_BASE}/chats/{chat_id}/messages/search", params=params)

    def recent_expired_subscribers(self) -> Any:
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/recent-expired",
                             params={"skip_users": "all"})


    def stories_feed(self) -> list:
        try:
            out = self.get_json(f"{API_BASE}/stories")
        except OFDeniedError:
            raise
        except OFAPIError as e:
            log_of.warning("stories_feed: OF refused GET /stories (%s); OF's web "
                           "client reads /stories/map now",
                           getattr(e.response, "status_code", None))
            raise
        if not isinstance(out, list) and not isinstance(
                out.get("list") if isinstance(out, dict) else None, list):
            log_of.warning("stories_feed: GET /stories answered no list (%s); OF's "
                           "web client reads /stories/map now", type(out).__name__)
        return out

    def streams_feed(self, *, limit: int = 10) -> dict:
        return self.get_json(f"{API_BASE}/streams/feed", params={"limit": limit})

    def my_stories_archive(self, *, limit: int = 20, offset: int = 0) -> dict:
        return self.get_json(f"{API_BASE}/stories/archive",
                             params={"limit": limit, "offset": offset})


    def _date_range_params(self, start: str | None, end: str | None) -> dict:
        from datetime import datetime, timedelta
        if not end: end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not start:
            start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        return {"startDate": start, "endDate": end}

    @staticmethod
    def _filter_params(keys) -> dict:
        return {f"filter[{k}]": k for k in keys or () if k}

    def earnings_chart(self, *, start: str | None = None, end: str | None = None,
                       with_total: bool = True, filter: list[str] | None = None,
                       monthly_total: bool = False) -> Any:
        # With no filter OF returns [] (blank chart): always name the series.
        if monthly_total:
            return self.get_json(f"{API_BASE}/earnings/chart", params={"monthlyTotal": 1})
        params = self._date_range_params(start, end)
        if with_total: params["withTotal"] = "true"
        params.update(self._filter_params(filter))
        return self.get_json(f"{API_BASE}/earnings/chart", params=params)

    def posts_chart(self, *, start: str | None = None, end: str | None = None,
                    with_total: bool = True, by: str | None = None) -> dict:
        params = self._date_range_params(start, end)
        if with_total: params["withTotal"] = "true"
        if by:
            params.update(self._filter_params([by, "posts"]))
        return self.get_json(f"{API_BASE}/posts/chart", params=params)

    def posts_top(self, *, start: str | None = None, end: str | None = None,
                  by: str = "purchases", limit: int = 10, offset: int | None = None) -> dict:
        params = self._date_range_params(start, end)
        params.update({"by": by, "limit": limit})
        if offset is not None:
            params["offset"] = offset
        return self.get_json(f"{API_BASE}/posts/top", params=params)

    def my_stats_overview(self, *, start: str | None = None, end: str | None = None,
                          by: str = "visitors") -> dict:
        params = self._date_range_params(start, end)
        params["by"] = by
        return self.get_json(f"{API_BASE}/users/me/stats/overview", params=params)

    def my_stats_top_posts(self, *, start: str | None = None, end: str | None = None,
                           limit: int = 10) -> dict:
        params = self._date_range_params(start, end)
        params["limit"] = limit
        params["skip_users"] = "all"
        return self.get_json(f"{API_BASE}/users/me/stats/top/post", params=params)

    def my_profile_stats(self, *, start: str | None = None, end: str | None = None,
                         limit: int = 10, by: str | None = None,
                         filter: list[str] | None = None) -> dict:
        params = self._date_range_params(start, end)
        params["limit"] = limit
        if by: params["by"] = by
        if filter: params["filter[]"] = list(filter)
        return self.get_json(f"{API_BASE}/users/me/profile/stats", params=params)

    def my_start_date(self) -> dict:
        return self.get_json(f"{API_BASE}/users/me/start-date-model")

    def qr_views(self) -> dict:
        return self.get_json(f"{API_BASE}/users/me/profile/views/qr")

    def sessions(self) -> list:
        return self.get_json(f"{API_BASE}/sessions")

    def social_buttons(self) -> list:
        return self.get_json(f"{API_BASE}/users/social/buttons")

    def social_media_providers(self) -> dict:
        data = self.get_json(f"{API_BASE}/init")
        providers = data.get("socialMediaProviders") if isinstance(data, dict) else None
        return {"socialMediaProviders": providers if isinstance(providers, list) else []}

    def users_links(self) -> list:
        return self.get_json(f"{API_BASE}/users/links")

    def stream_blocked_users(self, *, limit: int = 10, offset: int = 0, query: str = "") -> dict:
        params: dict[str, Any] = {"limit": limit}
        if offset: params["offset"] = offset
        if query: params["query"] = query
        return self.get_json(f"{API_BASE}/streams/users/blocked", params=params)

    def chargebacks_ratio(self, *, start: str | None = None, end: str | None = None) -> dict:
        return self.get_json(f"{API_BASE}/payouts/chargebacks/ratio",
                             params=self._date_range_params(start, end))


    def chargebacks(self, *, start: str | None = None, end: str | None = None,
                    limit: int = 10, offset: int = 0, marker: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if marker: params["marker"] = marker
        params.update(self._date_range_params(start, end))
        return self.get_json(f"{API_BASE}/payouts/chargebacks", params=params)

    def stats_top(self, kind: str, *, start: str | None = None, end: str | None = None) -> dict:
        return self.get_json(f"{API_BASE}/users/me/stats/top/{kind}",
                             params=self._date_range_params(start, end))

    def streaks(self, *, start: str | None = None, end: str | None = None) -> dict:
        return self.get_json(f"{API_BASE}/streaks", params=self._date_range_params(start, end))

    def streaks_top(self) -> dict:
        return self.get_json(f"{API_BASE}/streaks/top")

    def today_activity(self) -> dict:
        return self.get_json(f"{API_BASE}/users/me/stats/today-activity")

    def messages_chart(self, type: str, *, start: str | None = None,
                       end: str | None = None) -> dict:
        return self._with_total_chart(
            "/messages/queue/chart", [f"{type}_messages", f"{type}_messages_purchases"], start, end)

    def mass_message_buyers(self, queue_id: int, *, limit: int = 10, offset: int = 0,
                            marker: str | None = None, skip_users: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if skip_users: params["skip_users"] = skip_users
        else: params["skip_users_dups"] = 1
        if marker: params["marker"] = marker
        return self.get_json(f"{API_BASE}/messages/queue/{queue_id}/buyers", params=params)

    def subscribers_latest(self, *, by: str = "total", start: str | None = None,
                           end: str | None = None, offset: int = 0) -> dict:
        params = self._date_range_params(start, end)
        params.update({"by": by, "offset": offset})
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/latest", params=params)

    def subscribers_top(self, *, by: str = "total", start: str | None = None,
                        end: str | None = None, offset: int = 0) -> dict:
        params = self._date_range_params(start, end)
        params.update({"by": by, "offset": offset})
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/top", params=params)

    def fans_activity(self, *, format: str = "table", start: str | None = None,
                      end: str | None = None, time_zone: str = "UTC") -> dict:
        params: dict[str, Any] = {"format": format}
        params.update(self._date_range_params(start, end))
        params["timeZone"] = time_zone
        return self.get_json(f"{API_BASE}/fans-activity/list", params=params)

    def streams_top(self, *, by: str = "purchases", start: str | None = None,
                    end: str | None = None, limit: int = 10, offset: int = 0) -> dict:
        params = self._date_range_params(start, end)
        params.update({"limit": limit, "offset": offset, "by": by})
        return self.get_json(f"{API_BASE}/streams/top", params=params)

    def stories_top(self, *, by: str = "tips", start: str | None = None,
                    end: str | None = None, limit: int = 4, offset: int = 0) -> dict:
        params = self._date_range_params(start, end)
        params.update({"by": by, "offset": offset, "limit": limit})
        return self.get_json(f"{API_BASE}/stories/top", params=params)

    def promotions_stats(self, *, start: str | None = None, end: str | None = None,
                         limit: int = 10, offset: int = 0) -> dict:
        params: dict[str, Any] = {"offset": offset}
        params.update(self._date_range_params(start, end))
        params["limit"] = limit
        return self.get_json(f"{API_BASE}/promotions", params=params)

    def trials_stats(self, *, start: str | None = None, end: str | None = None,
                     limit: int = 10, offset: int = 0) -> dict:
        params: dict[str, Any] = {"offset": offset}
        params.update(self._date_range_params(start, end))
        params["limit"] = limit
        return self.get_json(f"{API_BASE}/trials/stats", params=params)

    def campaigns_stats(self, *, start: str | None = None, end: str | None = None,
                        limit: int = 10, offset: int = 0, field: str | None = None,
                        sort: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset, "pagination": 1}
        if field: params["field"] = field
        params.update(self._date_range_params(start, end))
        params.update({"with_deleted": 1, "sorting_deleted": 0, "stats": "true"})
        if sort: params["sort"] = sort
        return self.get_json(f"{API_BASE}/campaigns", params=params)


    def _amount_count_chart(self, path: str, start, end, with_total: Any = "true") -> dict:
        params = self._date_range_params(start, end)
        params.update({"withTotal": with_total, "withChart": "true"})
        params.update(self._filter_params(["chartAmount", "chartCount"]))
        return self.get_json(f"{API_BASE}{path}", params=params)

    def _stats_chart(self, path: str, start, end) -> dict:
        params = self._date_range_params(start, end)
        params["stats"] = 1
        return self.get_json(f"{API_BASE}{path}", params=params)

    def _with_total_chart(self, path: str, series: list, start, end) -> dict:
        params = self._date_range_params(start, end)
        params["withTotal"] = "true"
        params.update(self._filter_params(series))
        return self.get_json(f"{API_BASE}{path}", params=params)

    def payouts_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        return self._amount_count_chart("/payouts/chart", start, end)

    def referrals_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        return self._amount_count_chart("/payouts/referrals/chart", start, end, with_total=1)

    def chargebacks_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        return self._amount_count_chart("/payouts/chargebacks/chart", start, end)

    def promotions_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        return self._stats_chart("/promotions/chart", start, end)

    def trials_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        return self._stats_chart("/trials/chart", start, end)

    def campaigns_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        params = self._filter_params(["clicks", "claims"])
        params.update(self._date_range_params(start, end))
        return self.get_json(f"{API_BASE}/campaigns/chart", params=params)

    def stories_chart(self, *, by: str, start: str | None = None, end: str | None = None) -> dict:
        return self._with_total_chart("/stories/chart", [by, "stories"], start, end)

    def streams_chart(self, *, by: str, start: str | None = None, end: str | None = None) -> dict:
        return self._with_total_chart("/streams/chart", [by, "duration"], start, end)

    def stream_viewers(self, stream_id: int, *, limit: int = 10, offset: int = 0,
                       tips_only: bool = False) -> dict:
        params: dict[str, Any] = {"withFinishedViewers": "true", "onlyCurrentStreamTips": "true"}
        if tips_only: params["onlyWithTips"] = "true"
        params.update({"limit": limit, "offset": offset})
        return self.get_json(f"{API_BASE}/streams/{stream_id}/viewers", params=params)

    def story_viewers(self, story_id: int, *, limit: int = 10, offset: int = 0,
                      tips_only: bool = False) -> dict:
        params: dict[str, Any] = {"onlyWithTips": "true"} if tips_only else {}
        params.update({"limit": limit, "offset": offset})
        return self.get_json(f"{API_BASE}/stories/{story_id}/viewers", params=params)


    def post_stats(self, post_id: int) -> dict:
        return self.get_json(f"{API_BASE}/posts/{post_id}/stats", params={"withChart": "true"})

    def post_users(self, post_id: int, kind: str, *, limit: int = 10, offset: int = 0) -> dict:
        if kind not in ("buyers", "tips", "favorites"):
            raise ValueError(f"post user list must be buyers, tips or favorites, not {kind!r}")
        return self.get_json(f"{API_BASE}/posts/{post_id}/{kind}",
                             params={"limit": limit, "offset": offset})

    def offer_claims(self, offer_id: int, kind: str, *, limit: int = 10, offset: int = 0) -> dict:
        # OF reads at most 20 rows per call: limit > 20 with offset += limit silently skips fans, so walk at <= 20.
        key = {"promo": "promoId", "trial": "trial_id"}.get(kind)
        if key is None:
            raise ValueError(f"offer kind must be promo or trial, not {kind!r}")
        return self.get_json(f"{API_BASE}/subscriptions/subscribers",
                             params={"limit": limit, "offset": offset, "format": "infinite",
                                     f"filter[{key}]": offer_id})

    def campaign_claimers(self, campaign_id: int, *, limit: int = 10, offset: int = 0,
                          query: str | None = None) -> dict:
        params: dict[str, Any] = {"more": "true" if offset else "false", "limit": limit, "offset": offset}
        if query: params["query"] = query
        return self.get_json(f"{API_BASE}/campaigns/{campaign_id}/claimers", params=params)

    def payout_invoice(self, invoice_id: int, *, referral: bool = False):
        return self.get(f"{API_BASE}/payouts/download-approved-invoice",
                        params={"invoiceId": invoice_id, "app-token": APP_TOKEN,
                                "isRefbonus": 1 if referral else 0})

    def referrals(self, *, start: str | None = None, end: str | None = None,
                  offset: int = 0, marker: str | None = None,
                  only_performers: bool = False) -> dict:
        params = self._date_range_params(start, end)
        params["offset"] = offset
        if marker: params["marker"] = marker
        params["onlyPerformers"] = 1 if only_performers else 0
        return self.get_json(f"{API_BASE}/users/me/referrals", params=params)


    def bookmarks_all(self, *, limit: int = 10, offset: int = 0) -> dict:
        return self.get_json(f"{API_BASE}/posts/bookmarks/all/",
                             params={"format": "infinite", "limit": limit, "offset": offset, "skip_users": "all"})


    def referrals_balance(self) -> dict:
        return self.get_json(f"{API_BASE}/payments/referrals/balance")

    def referral_payouts(self, *, limit: int = 10, offset: int = 0, start: str | None = None,
                         end: str | None = None, marker: str | None = None) -> dict:
        return self.get_json(f"{API_BASE}/payouts/requests/referral",
                             params=self._payout_list_params(limit, offset, start, end, marker))


    def notification_settings(self, transport: str, *, group: int | None = None) -> list:
        params = {"group": group} if group is not None else None
        return self.get_json(f"{API_BASE}/users/settings/notifications/{transport}", params=params)


    def gif_trending(self, *, limit: int = 10, offset: int = 0) -> dict:
        return self.get_json(f"{API_BASE}/giphy/proxy/gifs/trending",
                             params={"limit": limit, "offset": offset})

    def gif_search(self, query: str, *, limit: int = 10, offset: int = 0) -> dict:
        return self.get_json(f"{API_BASE}/giphy/proxy/gifs/search",
                             params={"q": query, "limit": limit, "offset": offset})


    def message_templates(self, *, template: str | None = None) -> list:
        params: dict[str, Any] = {}
        if template:
            params["template"] = template
        return self.get_json(f"{API_BASE}/messages/templates",
                             params=params or None)


    def subscription_bundles(self) -> list:
        return self.get_json(f"{API_BASE}/subscriptions/bundles")


    def tracking_links(self, *, limit: int | None = None, offset: int = 0,
                       with_deleted: bool = False) -> Any:
        params: dict[str, Any] = {}
        if limit is not None:
            params.update({"limit": limit, "offset": offset, "pagination": 1})
        if with_deleted:
            params.update({"with_deleted": 1, "sorting_deleted": 0})
        return self.get_json(f"{API_BASE}/campaigns", params=params or None)

    def tracking_links_sorted(self, *, offset: int = 0, limit: int = 100,
                              field: str, sort: str) -> Any:
        return self.get_json(f"{API_BASE}/campaigns", params={
            "limit": int(limit), "offset": int(offset), "pagination": 1, "field": field, "sort": sort})


    def trial_links(self, *, offset: int = 0, limit: int = 100) -> list:
        # Paginated with a default page of 3: a bare call hides most links.
        return self.get_json(f"{API_BASE}/trials",
                             params={"offset": int(offset), "limit": int(limit)})

    def trial_links_sorted(self, *, offset: int = 0, limit: int = 100,
                           field: str | None = None, sort: str | None = None) -> Any:
        params: dict[str, Any] = {"limit": int(limit), "offset": int(offset), "pagination": 1}
        if field and sort:
            params["field"] = field
            params["sort"] = sort
        return self.get_json(f"{API_BASE}/trials", params=params)

    def trials_shared_with_me(self, *, offset: int = 0, limit: int = 100) -> Any:
        return self.get_json(f"{API_BASE}/trials/share-access",
                             params={"limit": int(limit), "offset": int(offset), "pagination": 1})

    def countries(self) -> Any:
        return self.get_json(f"{API_BASE}/countries", params={"all": 1})


    def tracking_links_shared_with_me(self, *, offset: int = 0, limit: int = 100,
                                      field: str | None = None, sort: str | None = None) -> Any:
        params: dict[str, Any] = {"limit": int(limit), "offset": int(offset), "pagination": 1,
                                  "with_deleted": 1, "sorting_deleted": 1, "stats": "true"}
        if field and sort:
            params["field"] = field
            params["sort"] = sort
        return self.get_json(f"{API_BASE}/campaigns/share-access", params=params)

from of_client import (  # noqa: E402
    API_BASE, APP_TOKEN, CHAT_MEDIA_KINDS, OFAPIError, OFDeniedError, log_of,
)
