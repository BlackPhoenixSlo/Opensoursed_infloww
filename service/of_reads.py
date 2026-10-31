"""OFClient's reads: the GET endpoints (chats, users, vault, stats, charts,
lists, referrals, settings). One part of `of_client.OFClient`."""
from __future__ import annotations

from typing import Any


class ReadsMixin:
    """Needs `_Transport.get`/`get_json`; calls no sibling mixin."""

    # ── Endpoints ───────────────────────────────────────────────

    def me(self) -> dict:
        """GET /api2/v2/users/me — sanity-check the session (no chat needed)."""
        return self.get_json(f"{API_BASE}/users/me")

    def list_chats(self, *, limit: int = 10, order: str = "recent",
                   offset: int = 0, filter: str | None = None,
                   list_id: int | str | None = None,
                   query: str | None = None,
                   skip_users: str | None = "all") -> dict:
        """GET /api2/v2/chats — list conversations.

        OF UI uses three orthogonal filters:
          - `filter`: one of {unread, pinned, priority} or None for all.
          - `list_id`: when set, only chats whose fan is in that custom list
            (folder) are returned. Combine with filter=None for "all in folder".
          - `query`: free-text search by fan name/username — captured curl
            from /my/chats/?q=… uses `query=` (NOT `search=`, which OF rejects
            with "Invalid filter" on this endpoint).

        All defaults match the captured DevTools curls (skip_users=all,
        order=recent). offset+limit are inclusive — i.e. offset=10&limit=10
        gives the 11th through 20th chat.

        `skip_users="all"` (the OF UI default) strips the heavy relationship
        flags (`subscribedOn`/`subscribedBy`) from each `withUser` — fine for the
        inbox list, but it's exactly what left the chat-scrape unable to classify
        peer-creators (source stuck as 'onlyfans'). Pass `skip_users=None` to omit
        the param and get the full `withUser` so callers can classify the source.
        """
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
        """GET /api2/v2/lists?isChat=true&format=infinite — fan-list 'folders'
        the user has created. The OF chat sidebar pins them as filter chips.
        `filter='can_pin_chat'` returns lists eligible for pinning."""
        params: dict[str, Any] = {
            "filter": filter, "isChat": "true", "skip_users": "all",
            "format": "infinite", "limit": limit, "offset": offset,
        }
        return self.get_json(f"{API_BASE}/lists", params=params)

    def get_messages(self, chat_id: str | int, *, limit: int = 10,
                     order: str = "desc", before_id: str | int | None = None,
                     offset: int | None = None) -> dict:
        """GET /api2/v2/chats/{chat_id}/messages — single page of history.

        Probed live (read-only): OF IGNORES `limit` and returns FEWER than asked
        (desc 50->34, 100->71; asc 50 was honored). NEVER assume the page size —
        always loop on `hasMore`.

        `before_id` maps to the `id` param, which ALWAYS means "older than id"
        (an upper bound) in BOTH orders — it only pages BACKWARD. So
        `order=desc` + `before_id=<oldest seen>` is the correct older-cursor.

        `offset` pages from a fixed position; pair it with `order=asc` to walk
        FORWARD from the convo START (`offset=0` returns the true first
        messages, bump it for more)."""
        params: dict[str, Any] = {"limit": limit, "order": order, "skip_users": "all"}
        if before_id is not None:
            params["id"] = before_id
        if offset is not None:
            params["offset"] = offset
        return self.get_json(f"{API_BASE}/chats/{chat_id}/messages", params=params)

    # ── Users ───────────────────────────────────────────────────

    def get_user(self, user_id_or_username: str | int) -> dict:
        """GET /api2/v2/users/{id_or_username} — full profile for a single user.
        Accepts a numeric id or a username string (OF resolves both)."""
        return self.get_json(f"{API_BASE}/users/{user_id_or_username}")

    def list_users(self, user_ids: list[str | int], *, view: str = "m") -> dict:
        """GET /api2/v2/users/list?{view}[]=ID1&{view}[]=ID2 — batch user lookup.

        `view` selects the depth of fields returned:
          - "m" (default): chat-list view — matches the `withUser._view: "m"` you
            get from /chats. Slim, just what's needed to render a chat list.
          - "x": extended view — more fields per user (subscribe state, etc.).

        OF accepts up to ~50 ids per call; chunk larger lists yourself.

        Returns a dict keyed by user-id string: `{"117183": {...}, "800000778": {...}}`.
        Use `.values()` if you need a flat iterable."""
        if not user_ids:
            return {}
        if view not in ("m", "x"):
            raise ValueError(f"view must be 'm' or 'x', got {view!r}")
        from urllib.parse import urlencode
        qs = urlencode([(f"{view}[]", str(uid)) for uid in user_ids])
        return self.get_json(f"{API_BASE}/users/list?{qs}")

    # ── Dashboard / init / notifications ───────────────────────

    def notifications(self, *, limit: int = 10, offset: int = 0,
                      type: str | None = None, related_user: int | None = None) -> dict:
        """GET /api2/v2/users/notifications — alerts feed.
        Note: prefix is /users/notifications, NOT /notifications (my earlier
        guess was wrong; captured via XHR audit). Working `type` filters use the
        PAST-TENSE singular: 'subscribed', 'tipped', 'commented', 'mentioned'
        (verified live 2026-06). Plural/gerund forms like 'subscribes'/
        'subscriptions' 400. Untyped returns ALL types and can be flooded by
        moderation events (`deactivated_media`) — always pass `type` when you
        want a specific feed."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if type: params["type"] = type
        # OF web's "View user's comments" (a chat's menu): the commented tab for one user.
        if related_user is not None: params["related_user"] = related_user
        return self.get_json(f"{API_BASE}/users/notifications", params=params)

    def notifications_count(self) -> dict:
        """GET /api2/v2/users/notifications/count — badge count per category."""
        return self.get_json(f"{API_BASE}/users/notifications/count")

    def release_form_mentions(self, *, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/release-forms/mentions — the Notifications page's Tags tab
        (posts the creator is tagged in). OF's own tab sends limit, offset,
        skip_users=all and format=infinite; returns {list, hasMore, lastId}, the
        list items in the notification shape."""
        return self.get_json(f"{API_BASE}/release-forms/mentions",
                             params={"limit": limit, "offset": offset,
                                     "skip_users": "all", "format": "infinite"})

    def my_settings(self) -> dict:
        """GET /api2/v2/users/me/settings — full settings dump."""
        return self.get_json(f"{API_BASE}/users/me/settings")

    def user_streams(self, user_id: str | int, *, limit: int = 8, offset: int = 0) -> dict:
        """GET /api2/v2/users/{user_id}/streams — a creator's past live streams
        (OF's Streaming dashboard, 8 a page, skip_users=all). Returns
        {list, hasMore}; items carry id, media (its thumb), viewsCount, startedAt."""
        return self.get_json(f"{API_BASE}/users/{user_id}/streams",
                             params={"limit": limit, "offset": offset, "skip_users": "all"})

    def _payout_list_params(self, limit, offset, start, end, marker) -> dict:
        """limit, offset, then OF's own paging (app.js 977600 `se` / `re`):
        startDate, endDate and marker, each only when given."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if start: params["startDate"] = start
        if end: params["endDate"] = end
        if marker: params["marker"] = marker
        return params

    def payout_requests(self, *, limit: int = 10, offset: int = 0, start: str | None = None,
                        end: str | None = None, marker: str | None = None) -> dict:
        """GET /api2/v2/payouts/requests — payout request history (Statements ›
        Payout requests). OF's page sends startDate, endDate, offset and marker;
        reply {list:[{invoiceId, createdAt, amount, currency, state, rejectReason}],
        marker} with no hasMore."""
        return self.get_json(f"{API_BASE}/payouts/requests",
                             params=self._payout_list_params(limit, offset, start, end, marker))

    def subscription_counts_all(self) -> dict:
        """GET /api2/v2/subscriptions/count/all — full breakdown (active/expired/blocked/...)."""
        return self.get_json(f"{API_BASE}/subscriptions/count/all")

    def subscribers_chart(self, *, start: str | None = None, end: str | None = None,
                          by: str | None = None) -> dict:
        """GET /api2/v2/subscriptions/subscribers/chart — OF Statistics >
        Subscriptions. Returns TWO daily series plus totals:
          • subscribes  — new-subscriber COUNT per day (free-inclusive)
          • earnings    — new PAID-subscriber revenue per day (0 on free pages)
          • subscribers — sum(subscribes[].count); OF's "N Subscribers" header
          • total/delta — earnings total + delta
        Use `subscribers` for a free-inclusive "new fans in window" count.
        `by` (total|renew|new) is what OF's Fans › Subscriptions tabs add."""
        params = self._date_range_params(start, end)
        if by: params["by"] = by
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/chart", params=params)

    def vault_media_processing(self) -> dict:
        """GET /api2/v2/vault/media/processing — uploads currently being processed."""
        return self.get_json(f"{API_BASE}/vault/media/processing")

    def labels(self) -> list:
        """GET /api2/v2/labels — post labels, `{list[{id,name,postsCount}], hasMore}`."""
        return self.get_json(f"{API_BASE}/labels")

    # ── User-facing search / lookup ────────────────────────────

    def search_users(self, query: str, *, limit: int = 10, offset: int = 0) -> list:
        """GET /api2/v2/users?query=... — search by name/username. Returns a list.

        OF's own search box ("Search users or posts": users/fetchSearchUsers,
        build 202610091632) sends `{limit, offset, query, view: "se"}`; the old
        `q=` key returned [] live (2026-10-17)."""
        return self.get_json(f"{API_BASE}/users", params={
            "limit": limit, "offset": offset, "query": query, "view": "se"})

    def performers_search(self, query: str, *, limit: int = 10, offset: int = 0) -> list:
        """GET /api2/v2/users/performers-search — creators only (the share
        dialog's username autocomplete, search-type "performers")."""
        return self.get_json(f"{API_BASE}/users/performers-search",
                             params={"limit": limit, "offset": offset, "query": query})

    def search_posts(self, query: str, *, limit: int = 10) -> Any:
        """GET /api2/v2/posts?query=... — the feed's posts search (posts/fetch
        with `query`, build 202610091632)."""
        return self.get_json(f"{API_BASE}/posts", params={
            "limit": limit, "query": query, "skip_users": "all", "format": "infinite"})

    def release_forms(self, *, limit: int = 20, offset: int = 0, filter: str = "all",
                      sort: str = "date:desc", name: str | None = None) -> Any:
        """GET /api2/v2/release-forms — the tag dialog's Release form tab
        (releaseForms/fetchFormsPage: `{limit, offset, filter, sort, name}`)."""
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
        """GET /api2/v2/posts/tagged-friend-users — creators eligible to be
        tagged in posts AND chat messages. Captured live 2026-05-23 from
        the OF web chat composer (referer was /my/chats/chat/{id}/), so
        despite the `/posts/` prefix this is the same endpoint OF uses for
        chat @-tags.

        Search is by `name=<query>` (OF rejects `search=`). Response shape
        is `{items, hasMore}` (NOT `{list, hasMore}` like vault endpoints).
        Filter `all` + sort `date:desc` mirror the captured call."""
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
        """GET /api2/v2/users/{user_id}/posts — posts owned by a creator.

        `type` filters: 'photo'|'video'|'audio'|'archived' (where allowed).
        `before_publish_time` is OF's cursor for older pages; pass the
        `tailMarker` string from the previous response (e.g.
        '1777499224.000000') to step backwards.
        `format='infinite'` makes OF return tailMarker/headMarker so the
        caller can stitch pages together."""
        params: dict[str, Any] = {"limit": limit, "skip_users": skip_users}
        if type: params["type"] = type
        if order: params["order"] = order
        if format: params["format"] = format
        if before_publish_time: params["beforePublishTime"] = before_publish_time
        return self.get_json(f"{API_BASE}/users/{user_id}/posts", params=params)

    # ── Subscribers (fans) ─────────────────────────────────────

    def subscribers(self, *, type: str = "active", limit: int = 10, offset: int = 0,
                    sort: str = "-users.last_activity", filter: str | None = None,
                    online: bool | None = None, min_spent: int | None = None,
                    min_tips: int | None = None) -> dict:
        """GET /api2/v2/subscriptions/subscribers — fans subscribed to me.
        `type` in {'active','expired','all'}. `filter` accepts 'attention',
        'recent', 'muted' depending on OF version.

        Object filters (mirror OF web's `filter[...]` query params):
          - `online=True`  → `filter[online]=1`  (only fans currently online)
          - `min_spent=N`  → `filter[total_spent]=N` (fans who spent ≥ N)
          - `min_tips=N`   → `filter[tips]=N`
        VERIFIED LIVE — OF's "Subscribers · online" list (referer
        /my/collections/user-lists/subscribers/active?online=1) hits exactly
        this with `filter[online]=1&format=infinite&more=true`."""
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
        """GET /api2/v2/subscriptions/subscribes — the accounts I subscribe TO.

        The other half of a `userLists: ["fans","following"]` broadcast: `fans` is
        `subscribers` above (my active subs), `following` is this (the creators I
        follow). `audiences.resolve_recipients_blocking` pages both to record who
        OF evaluated for a blast, so the engine can splice the blast into a
        replier's history without guessing at the audience.

        A 200 is captured in `library/of_api_reference/
        GET_api2_v2_subscriptions_subscribes.md` with the `{list: [...]}` envelope;
        the PARAMS are only known from OF's web client (type/limit/offset +
        `format=infinite` for the `hasMore` flag `_page_all_checked` trusts), which
        is why this is shaped like `subscribers` rather than measured. Callers must
        tolerate a bare list as well as the envelope — `_page_all_checked` does —
        and a crawl that comes back wrong fails CLOSED at the caller (no recipient
        record → no splice), never into the send path."""
        params: dict[str, Any] = {"type": type, "limit": limit, "offset": offset}
        if format:
            params["format"] = format
        return self.get_json(f"{API_BASE}/subscriptions/subscribes", params=params)

    def iter_online_subscribers(self, *, type: str = "active", page_size: int = 20,
                                max_fans: int = 1000) -> list[dict]:
        """Convenience: page through ALL currently-online subscribers and return
        the flat list of fan objects. OF caps `limit` at 20 for this list, so we
        walk `offset` until `hasMore` is false (or `max_fans` is hit)."""
        out: list[dict] = []
        seen: set[int] = set()
        offset = 0
        page_size = max(1, min(int(page_size), 20))
        # No-progress guard: some OF list endpoints IGNORE `offset` and report
        # hasMore=true forever (verified on /users/me/stats/messages/group,
        # 2026-07-04 incident) — dedup by fan id and stop on a page that adds
        # nothing new, else this loop re-reads page 1 to the max_fans ceiling
        # inside one thread-pool worker.
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
        """Fan ids of chats with UNREAD messages (fans waiting on a reply),
        newest-first, capped at `max_fans`. Pages `GET /chats?filter=unread`
        (the OF "Unread" inbox tab) and pulls `withUser.id` from each chat.
        Hand the list to `send_mass_message(included_users=...)`."""
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
            # No-progress guard — if OF ignores `offset` here (as it does on the
            # group-stats endpoint) the dedup set stops `out` from growing, the
            # `while len(out) < max_fans` cap can never be reached, and this
            # would spin FOREVER inside a thread-pool worker. A repeated page
            # means no cursor makes progress: stop.
            if added == 0:
                break
            if isinstance(page, dict) and not page.get("hasMore"):
                break
            offset += len(rows)
        return out[:max_fans]

    # subscriptions (creators I follow): no clean direct path found on this
    # account. Use /subscribers with type=all (these are subscribed *to me* though,
    # so this is for creator accounts). For "creators I'm subscribed to as a fan"
    # a different OF endpoint exists in some versions but isn't reliable here.

    # ── Posts (own + fan) ──────────────────────────────────────

    def list_posts(self, *, limit: int = 10, offset: int = 0,
                   order: str = "publish_date_desc",
                   skip_users: str = "all") -> dict:
        """GET /api2/v2/posts — my posts."""
        return self.get_json(
            f"{API_BASE}/posts",
            params={"limit": limit, "offset": offset, "order": order, "skip_users": skip_users},
        )

    def get_post(self, post_id: int | str) -> dict:
        """GET /api2/v2/posts/{post_id} — single post detail with media."""
        return self.get_json(f"{API_BASE}/posts/{post_id}")

    def post_comments(self, post_id: int | str, *, limit: int = 20, offset: int = 0,
                      order: str = "publish_date_desc") -> dict:
        """GET /api2/v2/posts/{post_id}/comments — comments on a post.

        Works on YOUR posts. On other creators' posts OF may 404 with
        'User cannot comment' if the post has comments disabled."""
        return self.get_json(
            f"{API_BASE}/posts/{post_id}/comments",
            params={"limit": limit, "offset": offset, "order": order},
        )

    # ── Vault (own media library) ──────────────────────────────

    def vault_media(self, *, limit: int = 24, offset: int = 0,
                    type: str = "all", list_id: int | None = None,
                    sort: str = "desc", field: str = "recent",
                    query: str | None = None,
                    before_publish_date: str | None = None) -> dict:
        """GET /api2/v2/vault/media — vault items.

        `type`: 'all'|'photo'|'video'|'gif'|'audio' — **OF uses `?type=`,
        not `?filter=`**. The latter is silently ignored, which we found out
        when filter=video returned photos.
        `list_id`: restrict to a vault list/folder. OF takes this on the
        `list` param (replacing the default 'all'), NOT as a separate
        `list_id` — sending both silently ignores the filter.
        `sort` / `field`: ordering. **`sort=asc` IS honored server-side**
        (verified live: asc → 2018 items, desc → 2026 items) — OF's field name
        is `sort`, values `asc`/`desc`, with `field=recent`.
        `query`: OF-native full-text vault search. The wire param is **`query`**
        (verified live: `query=bikini` narrowed 50→5; `search`/`q`/`text` are
        silently ignored). Empty/None omits it.
        `before_publish_date`: OF's "Go to date" (`beforePublishDate=YYYY-MM-DD`,
        the picked day; read from OF's web bundle). None ("All time") omits it."""
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
        """GET /api2/v2/vault/media/{id} — a single vault item by its id.

        OF exposes a real by-id read here (verified live): the response is one
        media dict with the SAME shape as an item inside `vault_media()['list']`
        — `files.thumb/squarePreview/preview` for thumbnails, `type`, `duration`,
        `videoSources`, etc. There is NO batch form (`?ids[]=` is silently
        ignored and returns the default page), so callers resolve one id per
        call. A deleted/unknown id raises OFAPIError 404 'Media Not Found'.

        Used to resolve already-saved per-slot brain images (`time_images`,
        which store bare media ids) back to thumbnails — the picker only ever
        returned full media for freshly-picked items, never the saved ids."""
        return self.get_json(f"{API_BASE}/vault/media/{int(media_id)}")

    def vault_lists(self, *, view: str = "main", limit: int = 10, offset: int = 0,
                    query: str | None = None) -> dict:
        """GET /api2/v2/vault/lists — vault folders / lists.
        The mandatory `view` value is **`main`** (captured from OF's web app
        XHR; every other value returns 400 'Bad view param').
        `query`: the folder column's Search (OF's web bundle sends `query=`;
        an empty search sends none)."""
        params: dict[str, Any] = {"view": view, "limit": limit, "offset": offset}
        if query and query.strip():
            params["query"] = query.strip()
        return self.get_json(f"{API_BASE}/vault/lists", params=params)

    # ── Payouts: balance + eligibility ─────────────────────────

    def payout_balances(self) -> dict:
        """GET /api2/v2/payouts/balances — current balance + breakdown."""
        return self.get_json(f"{API_BASE}/payouts/balances")

    def payout_check_receive(self) -> dict:
        """GET /api2/v2/payouts/check-receive — eligibility for next payout."""
        return self.get_json(f"{API_BASE}/payouts/check-receive")

    # ── Settings ───────────────────────────────────────────────

    def settings_story(self) -> dict:
        """GET /api2/v2/users/settings/story — story settings (`allowReplyFrom`)."""
        return self.get_json(f"{API_BASE}/users/settings/story")

    # ── Scheduling (separate API from /messages/queue) ─────────

    def schedules(self, *, publish_date: str | None = None,
                  publish_date_end: str | None = None,
                  time_zone: str = "Europe/Ljubljana",
                  limit: int = 20) -> dict:
        """GET /api2/v2/schedules — calendar view of scheduled chats + posts.
        Dates are ISO yyyy-mm-dd. OF wraps filters as `filter[publishDate]=...`."""
        params: dict[str, Any] = {"limit": limit}
        if publish_date:     params["filter[publishDate]"] = publish_date
        if publish_date_end: params["filter[publishDateEnd]"] = publish_date_end
        params["filter[timeZone]"] = time_zone
        return self.get_json(f"{API_BASE}/schedules", params=params)

    def schedules_later_chat(self, *, limit: int = 10) -> dict:
        """GET /api2/v2/schedules/later/chat — chats scheduled for the future
        (this is what OF's 'Queue' tab actually displays — distinct from
        /messages/queue which is older API)."""
        return self.get_json(f"{API_BASE}/schedules/later/chat", params={"limit": limit})

    def schedules_later_post(self, *, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/schedules/later/post — posts scheduled for the future.

        Paged: `offset` walks past the first page. A creator with a queue longer
        than `limit` otherwise never shows the far-future entries, and the vault
        sweep's whole job is finding a carrier scheduled 30 days out.
        """
        return self.get_json(f"{API_BASE}/schedules/later/post",
                             params={"limit": limit, "offset": offset})

    # ── User lists (fan lists) ─────────────────────────────────

    def get_lists(self, *, limit: int = 20, offset: int = 0) -> dict:
        """GET /api2/v2/lists — my custom fan lists.

        `format=infinite` forces OF to return the `{list, hasMore}` envelope
        instead of a bare array (which it does without the flag on some
        builds). The chat-folder picker also uses this flag — without it,
        the audience picker would silently get an empty response on
        accounts where OF returns the alternate shape."""
        return self.get_json(
            f"{API_BASE}/lists",
            params={"limit": limit, "offset": offset, "format": "infinite"},
        )

    def get_list(self, list_id: int | str) -> dict:
        """GET /api2/v2/lists/{list_id} — list metadata."""
        return self.get_json(f"{API_BASE}/lists/{list_id}")

    def list_users_in(self, list_id: int | str, *, limit: int = 20, offset: int = 0, query: str | None = None) -> dict:
        """GET /api2/v2/lists/{list_id}/users — fans in a list. `query`: Collections' Search users
        (OF's web client sends it as `query`, module 138255)."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if query:
            params["query"] = query
        return self.get_json(f"{API_BASE}/lists/{list_id}/users", params=params)

    def list_posts_in(self, list_id: int | str, *, limit: int = 10, offset: int = 0, type: str | None = None) -> dict:
        """GET /api2/v2/lists/{list_id}/posts — a list's Posts tab: its users' posts, newest first,
        `{list, hasMore, nextOffset}`, each post's author only `{id}` (skip_users=all; OF's web client
        reads them with /users/list). `type`: the tab's chip (photos, videos, audios, other, locked)."""
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if type:
            params["type"] = type
        params["skip_users"] = "all"
        return self.get_json(f"{API_BASE}/lists/{list_id}/posts", params=params)

    # ── Money: statements, transactions, payouts ───────────────

    # statements (payout history list): no direct path found that returns 200 here.
    # Likely creator-only and surfaced via the /payouts/stats time-series instead.
    # Use `earning_stats()` for the data the UI actually displays.

    def transactions(self, *, limit: int = 20, offset: int = 0,
                     type: str | None = None,
                     start: str | None = None, end: str | None = None,
                     start_date: str | None = None, marker: int | str | None = None,
                     tips_source: str | None = None) -> dict:
        """GET /api2/v2/payouts/transactions — every earning event (tip, sub, ppv).
        `type` like 'tip'|'subscribes'|'message'|'post'|None.

        Statistics › Statements › Earnings (OF app.js module 977600 `te`) pages
        this list with `startDate` (the period start), `marker` (first page: the
        period end as a unix timestamp; then the response's `nextMarker`), `type`
        and, on the Tips sub-tabs, `tipsSource` (profile|post_all|chat|stream|
        story). OF sends no endDate. Each is added only when given, so callers
        that do not pass them send what they always sent."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if type:  params["type"] = type
        if start: params["start"] = start
        if end:   params["end"] = end
        if start_date: params["startDate"] = start_date
        if marker is not None: params["marker"] = marker
        if tips_source: params["tipsSource"] = tips_source
        return self.get_json(f"{API_BASE}/payouts/transactions", params=params)

    def earning_stats(self, *, by: str = "day",
                      start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/payouts/stats — time-series totals.
        `by` in {'day','week','month'}."""
        params: dict[str, Any] = {"by": by}
        if start: params["start"] = start
        if end:   params["end"] = end
        return self.get_json(f"{API_BASE}/payouts/stats", params=params)

    # ── Stories / Highlights ───────────────────────────────────

    def user_stories(self, user_id: str | int) -> dict:
        """GET /api2/v2/users/{user_id}/stories — a creator's stories."""
        return self.get_json(f"{API_BASE}/users/{user_id}/stories")

    def user_highlights(self, user_id: str | int) -> dict:
        """GET /api2/v2/users/{user_id}/stories/highlights — a creator's highlights."""
        return self.get_json(f"{API_BASE}/users/{user_id}/stories/highlights")

    def highlight(self, highlight_id: int) -> dict:
        """GET /api2/v2/stories/highlights/{id} — one highlight with its stories,
        as OF's profile opens it (build 202610161317, module 502365 `g`, store
        action fetchHighlightsById: normalizr's `highlights` entity, `{stories:
        [story, ...]}`, stories in play order)."""
        return self.get_json(f"{API_BASE}/stories/highlights/{int(highlight_id)}")

    def user_photos(self, user_id: str | int, *, limit: int = 10, offset: int = 0) -> list:
        """GET /api2/v2/users/{user_id}/posts/photos — photo posts only."""
        return self.get_json(f"{API_BASE}/users/{user_id}/posts/photos",
                             params={"limit": limit, "offset": offset})

    def user_videos(self, user_id: str | int, *, limit: int = 10, offset: int = 0) -> list:
        """GET /api2/v2/users/{user_id}/posts/videos — video posts only."""
        return self.get_json(f"{API_BASE}/users/{user_id}/posts/videos",
                             params={"limit": limit, "offset": offset})

    # ── Promotions / trials / tracking links ───────────────────

    def promotions(self, *, offset: int = 0, limit: int = 100) -> dict:
        """GET /api2/v2/promotions — my subscription promotions.

        PAGINATED. Verified live 2026-07-22 (Ava): the default page is only 10
        items, `limit` is honoured to at least 100, and — importantly —
        `hasMore` stayed true past offset 180 on a 230+ promo history. Do NOT
        loop on hasMore; stop on a short or empty page. Reading page 1 alone
        makes an older-but-LIVE promo look absent, which promo_reactivate would
        read as "expired" and re-create.
        """
        return self.get_json(f"{API_BASE}/promotions",
                             params={"offset": int(offset), "limit": int(limit)})

    # tracking_links: no direct path found on this account. May be hidden under
    # creator-tier features or surfaced through /init only.

    # ── Chat extras: queue (scheduled), single chat ────────────

    def get_chat(self, chat_id: str | int) -> dict:
        """GET /api2/v2/chats/{chat_id} — full chat details (richer than list item)."""
        return self.get_json(f"{API_BASE}/chats/{chat_id}")

    def scheduled_messages(self, *, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/messages/queue — messages scheduled for the future."""
        return self.get_json(
            f"{API_BASE}/messages/queue",
            params={"limit": limit, "offset": offset},
        )

    def queued_message(self, queue_id: int) -> dict:
        """GET /api2/v2/messages/queue/{queue_id}?format=scheduled — one queued
        (scheduled or saved-for-later) mass message, as OF's own New message
        page loads it to edit it (`204607.f`, chats-send `getMessageScheduledQueue`):
        its text, media, price, `scheduledAt` (none: saved for later) and
        audience (`userIds`, `userLists`, `excludedLists`)."""
        return self.get_json(f"{API_BASE}/messages/queue/{queue_id}",
                             params={"format": "scheduled"})

    def mass_message_history(self, *, start_date: str, end_date: str,
                             limit: int = 50, offset: int = 0) -> dict:
        """GET /api2/v2/users/me/stats/messages/group — past mass-message
        broadcasts in the date range.

        `start_date` / `end_date` are 'YYYY-MM-DD HH:MM:SS' strings (OF's
        engagement stats page uses local time; we pass through whatever
        the caller hands us). Response shape:
          `{hasMore, items: [{id, date, text, giphyId, mediaCount, media,
            sentCount, viewedCount, isCanceled, canUnsend, unsendSeconds,
            template:'group', ...}]}`

        Each `id` is the queue id — can be passed to cancel_scheduled to
        unsend the broadcast from EVERY recipient. OF reports
        `unsendSeconds=1000000` and `canUnsend=true` on mass sends well
        past the per-chat 24h window — mass-message unsend has no edit
        window in practice."""
        return self.engagement_messages("group", start_date=start_date, end_date=end_date,
                                        limit=limit, offset=offset)

    def engagement_messages(self, type: str, *, start_date: str, end_date: str,
                            limit: int = 50, offset: int = 0,
                            query: str | None = None) -> dict:
        """GET /api2/v2/users/me/stats/messages/{group|direct} — Statistics ›
        Engagement › Messages (Mass messages / Direct messages tabs), as OF's
        client (app.js module 977600 `ge`) sends it: startDate, endDate, limit,
        offset, plus `query` for the tab's search box. OF pages without a query
        by moving endDate to the last item's date; with a query it pages by
        offset. Response {hasMore, items:[message]}."""
        params: dict[str, Any] = {"startDate": start_date, "endDate": end_date,
                                  "limit": limit, "offset": offset}
        if query:
            params["query"] = query
        return self.get_json(f"{API_BASE}/users/me/stats/messages/{type}", params=params)

    def get_pinned_messages(self, chat_id: str | int, *, limit: int = 50) -> list[dict]:
        """GET /api2/v2/chats/{chat_id}/messages?filter=pinned — a chat's pinned
        messages. ONE call, ONE page, the rows only.

        `filter=pinned` is the ONLY form OF honours. `pinned=1` and `isPinned=1`
        are silently IGNORED — they return an ordinary unfiltered page, which a
        caller that trusts the param reads as "every message is pinned". Probed
        read-only against live threads.

        Returns the list rather than OF's envelope ON PURPOSE, because the
        envelope's `hasMore` LIES on this filter: probed live it came back true
        on a two-row response, and `offset=2` then returned nothing. Handing back
        the rows makes the field that cannot be trusted unreachable. A pinned
        list is a handful of messages by construction, so one page is all of it —
        do not add pagination here."""
        payload = self.get_json(
            f"{API_BASE}/chats/{chat_id}/messages",
            params={"limit": limit, "order": "desc", "skip_users": "all",
                    "filter": "pinned"},
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
        """GET /api2/v2/chats/{chat_id}/media — messages in this chat that
        contain media.

        `kind` ("photos" | "videos" | "audios") is OF web's gallery type
        tab, a PATH segment: /chats/{chat_id}/media/photos (its chats API
        module, `fetchAndGetChatsUsersMedia`); OF has no query param for it.

        OF's gallery tabs back onto this one endpoint with different
        query-param combinations:
          • Default — every media-bearing message (free + PPV, sent +
            received). Useful for "show unsold media" surfaces.
          • `purchased=1` + `from_user=<creator_user_id>` → "Purchased"
            tab. ONLY the PPVs the fan actually paid for, with the
            creator's outbound messages only. This is what the OF web
            UI uses at /my/chats/chat/{id}/gallery/purchased and what we
            want for the FanDrawer's "Sales" section.
          • `opened=1` is a DIFFERENT filter (items the fan has viewed,
            includes free messages). Don't confuse with `purchased=1`.
          • `last_id=<previous nextLastId>` is the cursor; `offset` is
            kept for the legacy paginated form OF still accepts.
        """
        # OF web's gallery sends no offset (its cursor is last_id); only a legacy offset page names one.
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
        """GET /api2/v2/chats/{chat_id}/messages/search?query=… — search the
        full history of one chat. Returns a flat list of matching message
        IDs (newest first), e.g. [8099903898601, 7813771789577]. Empty
        list if no matches. OF's response is just ids — callers fetch
        previews from the regular messages cache or page back if needed.

        Verified live 2026-05-19 against OF web's chat-search dropdown.
        Param is `query`, NOT `text`; OF rejects the latter silently."""
        params: dict[str, Any] = {"query": query}
        # OF web's pinned page searches its pins only: filter=pinned.
        if filter: params["filter"] = filter
        return self.get_json(f"{API_BASE}/chats/{chat_id}/messages/search", params=params)

    def recent_expired_subscribers(self) -> Any:
        """GET /api2/v2/subscriptions/subscribers/recent-expired?skip_users=all —
        fans whose subscription to me lapsed recently. The re-engagement target
        pool. Verified live."""
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/recent-expired",
                             params={"skip_users": "all"})

    # ── Stories feed (for me as a fan) ─────────────────────────

    def stories_feed(self) -> list:
        """GET /api2/v2/stories — all stories from creators I follow.

        OF's own web client (build 202610161317, module 502365) no longer
        reads this path: its strip reads GET /stories/map[?list_id=] (one stub
        per creator, `{storyId, userId, ...}`, no profile) and then
        GET /stories/items?map[<userId>]=<storyId> for the media. Not moved
        here: the strip needs each creator's profile too, and neither answer's
        fields are checked live (02-gaps G5). Until then a refusal or an
        answer with no list in it is logged, so a retired /stories can't empty
        the strip silently."""
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
        """GET /api2/v2/streams/feed — the live and scheduled streams Home's
        story strip shows (build 202610161317, module 622365 `GQ`, store action
        fetchStreamsFeed): `{list: [stream, ...]}`, each with `user`,
        `isScheduled`, `isActive`, `startedAt`, `scheduledAt`, `thumbUrl` and a
        scheduled one's cover `media`. OF's client sends limit=10 and
        skip_users=all, then reads each creator with users/list; asked here
        without skip_users so each stream keeps its creator (as `chats`'s
        skip_users=None does), which is unchecked live (status-stories.md)."""
        return self.get_json(f"{API_BASE}/streams/feed", params={"limit": limit})

    def my_stories_archive(self, *, limit: int = 20, offset: int = 0) -> dict:
        """GET /api2/v2/stories/archive — my own archived (expired) stories."""
        return self.get_json(f"{API_BASE}/stories/archive",
                             params={"limit": limit, "offset": offset})

    # ── Analytics / charts ─────────────────────────────────────
    # All these accept start/end ISO datetime params. The OF UI calls them
    # with `startDate=YYYY-MM-DD HH:MM:SS` (space-separated, URL-encoded).
    # Default range is 30 days.

    def _date_range_params(self, start: str | None, end: str | None) -> dict:
        from datetime import datetime, timedelta
        if not end: end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not start:
            start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        return {"startDate": start, "endDate": end}

    @staticmethod
    def _filter_params(keys) -> dict:
        """OF's `filter` object, serialised the way its client does (app.js
        module 977434 `Zq`): {k: k} → `filter[k]=k`. OF's chart endpoints only
        return the series named here — /earnings/chart answers [] without it."""
        return {f"filter[{k}]": k for k in keys or () if k}

    def earnings_chart(self, *, start: str | None = None, end: str | None = None,
                       with_total: bool = True, filter: list[str] | None = None,
                       monthly_total: bool = False) -> Any:
        """GET /api2/v2/earnings/chart — Statistics earnings series.

        OF's client (app.js module 977600) always names the series it wants:
          • Statements sidebar, per category c in total|subscribes|tips|messages|
            post|stream (+ call, tips_stream): filter[{c}_count], filter[{c}_amount]
          • Overview: filter[total_amount|subscribes_amount|tips_amount|
            tips_stream_amount|post_amount|messages_amount|ref_amount|stream_amount]
          • Overview monthly bars: `monthlyTotal=1` alone (no dates, no filter).
        With no filter OF returns [] — the blank-chart bug. The reply is keyed by
        category, not by filter name: {c: {chartAmount, chartCount?, total, gross,
        delta}} (chartCount only when {c}_count was asked)."""
        if monthly_total:
            return self.get_json(f"{API_BASE}/earnings/chart", params={"monthlyTotal": 1})
        params = self._date_range_params(start, end)
        if with_total: params["withTotal"] = "true"
        params.update(self._filter_params(filter))
        return self.get_json(f"{API_BASE}/earnings/chart", params=params)

    def posts_chart(self, *, start: str | None = None, end: str | None = None,
                    with_total: bool = True, by: str | None = None) -> dict:
        """GET /api2/v2/posts/chart — post performance time-series. OF's
        Engagement › Posts sends filter[{by}]={by}&filter[posts]=posts (by in
        purchases|tips|views|likes|comments); without `by` only `posts` comes back."""
        params = self._date_range_params(start, end)
        if with_total: params["withTotal"] = "true"
        if by:
            params.update(self._filter_params([by, "posts"]))
        return self.get_json(f"{API_BASE}/posts/chart", params=params)

    def posts_top(self, *, start: str | None = None, end: str | None = None,
                  by: str = "purchases", limit: int = 10, offset: int | None = None) -> dict:
        """GET /api2/v2/posts/top?by=purchases — top performing posts.
        `by` in {purchases,likes,comments,views,...}. `offset` pages the list
        (OF's Engagement › Posts infinite scroll); sent only when given."""
        params = self._date_range_params(start, end)
        params.update({"by": by, "limit": limit})
        if offset is not None:
            params["offset"] = offset
        return self.get_json(f"{API_BASE}/posts/top", params=params)

    def my_stats_overview(self, *, start: str | None = None, end: str | None = None,
                          by: str = "visitors") -> dict:
        """GET /api2/v2/users/me/stats/overview — visitors/engagement overview."""
        params = self._date_range_params(start, end)
        params["by"] = by
        return self.get_json(f"{API_BASE}/users/me/stats/overview", params=params)

    def my_stats_top_posts(self, *, start: str | None = None, end: str | None = None,
                           limit: int = 10) -> dict:
        """GET /api2/v2/users/me/stats/top/post — my best-performing posts."""
        params = self._date_range_params(start, end)
        params["limit"] = limit
        params["skip_users"] = "all"
        return self.get_json(f"{API_BASE}/users/me/stats/top/post", params=params)

    def my_profile_stats(self, *, start: str | None = None, end: str | None = None,
                         limit: int = 10, by: str | None = None,
                         filter: list[str] | None = None) -> dict:
        """GET /api2/v2/users/me/profile/stats — visitor source breakdown
        (Statistics > Reach in OF UI). OF's client (module 977600 `_`) sends
        startDate, endDate, limit, `by` (total|guests|users: the All / Guests /
        Users chips) and, per block, `filter[]` = chart | topDomains |
        topCountries. `by` and `filter` are added only when given. topCountries
        answers {rows: [{rank, countryCode, countryName, viewsCount}], hasMore,
        totals: {guests, users}} — the totals as strings."""
        params = self._date_range_params(start, end)
        params["limit"] = limit
        if by: params["by"] = by
        if filter: params["filter[]"] = list(filter)
        return self.get_json(f"{API_BASE}/users/me/profile/stats", params=params)

    def my_start_date(self) -> dict:
        """GET /api2/v2/users/me/start-date-model — when I became a creator.
        Used by OF Statistics to range-cap charts."""
        return self.get_json(f"{API_BASE}/users/me/start-date-model")

    def qr_views(self) -> dict:
        """GET /api2/v2/users/me/profile/views/qr — the QR code's scan count
        (`{count}`), as OF's QR code settings page reads it."""
        return self.get_json(f"{API_BASE}/users/me/profile/views/qr")

    def sessions(self) -> list:
        """GET /api2/v2/sessions — the account's login sessions, as OF's Account >
        Login sessions page reads them (settings-sessions.js: a list of
        {sessionId, client, os, brand, ipAddress, countryName, loginMessage,
        lastActivity, isCurrent}). Read-only: OF's DELETE /sessions ("Close all
        sessions") has no method here."""
        return self.get_json(f"{API_BASE}/sessions")

    def stream_blocked_users(self, *, limit: int = 10, offset: int = 0, query: str = "") -> dict:
        """GET /api2/v2/streams/users/blocked — the users blocked from joining the
        model's streams (`{list, hasMore}`), as OF's Streaming > Blocked users page
        reads them: `limit` always, `offset` and `query` only when set."""
        params: dict[str, Any] = {"limit": limit}
        if offset: params["offset"] = offset
        if query: params["query"] = query
        return self.get_json(f"{API_BASE}/streams/users/blocked", params=params)

    def chargebacks_ratio(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/payouts/chargebacks/ratio — chargeback-rate risk metric."""
        return self.get_json(f"{API_BASE}/payouts/chargebacks/ratio",
                             params=self._date_range_params(start, end))

    # ── Statistics pages (OF app.js module 977600, the `statistic` store) ──
    # Every path and param below is copied from OF's own client, not guessed.
    # OF's page size (`Jg`) is 10. All dates are 'YYYY-MM-DD HH:mm:ss'.

    def chargebacks(self, *, start: str | None = None, end: str | None = None,
                    limit: int = 10, offset: int = 0, marker: str | None = None) -> dict:
        """GET /api2/v2/payouts/chargebacks — Statements › Chargebacks list
        (module 874727 `B`, called with offset, marker, startDate, endDate,
        limit=10). Response {list:[dispute], marker (a number)} with no hasMore:
        OF's page takes a full page (list.length == limit) as "more". Rows carry
        createdAt and a `payment` (createdAt, amount, fee, net) plus the fan."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if marker: params["marker"] = marker
        params.update(self._date_range_params(start, end))
        return self.get_json(f"{API_BASE}/payouts/chargebacks", params=params)

    def stats_top(self, kind: str, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/users/me/stats/top/{message|stream|story|fan} —
        Overview › Top highlights cards. Only startDate/endDate (top/post, which
        adds skip_users=all, is `my_stats_top_posts`). Each answers an object
        keyed by metric, each value an item or null: message {purchases}, stream
        {purchases, tips, views, likes, comments}, story {tips, views, likes,
        comments}, fan {total, subscriptions, tips, messages, streams}."""
        return self.get_json(f"{API_BASE}/users/me/stats/top/{kind}",
                             params=self._date_range_params(start, end))

    def streaks(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/streaks?startDate&endDate — Overview › Streaks calendar,
        response {list:[streak], hasMore}; a streak is {id, startDate, endDate,
        isActive, daysCount, postsCount, storiesCount, chatsCount,
        streamsDuration, frozenDays:[date]}."""
        return self.get_json(f"{API_BASE}/streaks", params=self._date_range_params(start, end))

    def streaks_top(self) -> dict:
        """GET /api2/v2/streaks/top — the longest streak: one streak object (the
        /streaks row fields), or empty when there is none."""
        return self.get_json(f"{API_BASE}/streaks/top")

    def today_activity(self) -> dict:
        """GET /api2/v2/users/me/stats/today-activity — today's {stories, posts,
        chats, streams} counts; any above 0 keeps the streak."""
        return self.get_json(f"{API_BASE}/users/me/stats/today-activity")

    def messages_chart(self, type: str, *, start: str | None = None,
                       end: str | None = None) -> dict:
        """GET /api2/v2/messages/queue/chart — Engagement › Messages chart and
        totals per tab: filter[{type}_messages], filter[{type}_messages_purchases]
        with withTotal (type group|direct). Reply {<t>_messages: {chart, total,
        delta}, <t>_messages_purchases: {chart, total, delta}}."""
        params = self._date_range_params(start, end)
        params["withTotal"] = "true"
        params.update(self._filter_params([f"{type}_messages", f"{type}_messages_purchases"]))
        return self.get_json(f"{API_BASE}/messages/queue/chart", params=params)

    def mass_message_buyers(self, queue_id: int, *, limit: int = 10, offset: int = 0,
                            marker: str | None = None, skip_users: str | None = None) -> dict:
        """GET /api2/v2/messages/queue/{id}/buyers — who bought a mass message
        (module 204607 `b`): limit, offset, marker, and skip_users — or
        skip_users_dups=1 when skip_users is not sent."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if skip_users: params["skip_users"] = skip_users
        else: params["skip_users_dups"] = 1
        if marker: params["marker"] = marker
        return self.get_json(f"{API_BASE}/messages/queue/{queue_id}/buyers", params=params)

    def subscribers_latest(self, *, by: str = "total", start: str | None = None,
                           end: str | None = None, offset: int = 0) -> dict:
        """GET /api2/v2/subscriptions/subscribers/latest — Fans › Subscriptions
        table, `by` total|renew|new (OF's All / Renews / New tabs), paged by
        offset in steps of 10. Response {users:[fan], hasMore}; each fan's
        subscribedOnData carries price, subscribeAt, expiredAt."""
        params = self._date_range_params(start, end)
        params.update({"by": by, "offset": offset})
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/latest", params=params)

    def subscribers_top(self, *, by: str = "total", start: str | None = None,
                        end: str | None = None, offset: int = 0) -> dict:
        """GET /api2/v2/subscriptions/subscribers/top — Fans › Top fans, `by`
        total|subscribes|tips|messages|post|streams. Response {users, hasMore};
        each fan's subscribedOnData carries totalSumm, subscribesSumm, tipsSumm,
        messagesSumm, postsSumm, streamsSumm."""
        params = self._date_range_params(start, end)
        params.update({"by": by, "offset": offset})
        return self.get_json(f"{API_BASE}/subscriptions/subscribers/top", params=params)

    def fans_activity(self, *, format: str = "table", start: str | None = None,
                      end: str | None = None, time_zone: str = "UTC") -> dict:
        """GET /api2/v2/fans-activity/list — Fans › Fans activity: format=table
        (the weekday sectors) or format=hours (the hourly bars), startDate,
        endDate and the viewer's IANA timeZone. Reply `.data`: table {Mon..Sun:
        {<hour 0-23>: {ratio}}}, hours [{ratio}] x 24."""
        params: dict[str, Any] = {"format": format}
        params.update(self._date_range_params(start, end))
        params["timeZone"] = time_zone
        return self.get_json(f"{API_BASE}/fans-activity/list", params=params)

    def streams_top(self, *, by: str = "purchases", start: str | None = None,
                    end: str | None = None, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/streams/top — Engagement › Streaming list, `by`
        purchases|tips|views|likes|comments. Response {items, hasMore}."""
        params = self._date_range_params(start, end)
        params.update({"limit": limit, "offset": offset, "by": by})
        return self.get_json(f"{API_BASE}/streams/top", params=params)

    def stories_top(self, *, by: str = "tips", start: str | None = None,
                    end: str | None = None, limit: int = 4, offset: int = 0) -> dict:
        """GET /api2/v2/stories/top — Engagement › Stories list, `by`
        tips|views|likes|comments (OF asks 4 at a time). Response {items, hasMore}."""
        params = self._date_range_params(start, end)
        params.update({"by": by, "offset": offset, "limit": limit})
        return self.get_json(f"{API_BASE}/stories/top", params=params)

    def promotions_stats(self, *, start: str | None = None, end: str | None = None,
                         limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/promotions?offset&startDate&endDate&limit — Reach ›
        Promotions table (module 977600 `L`). Response {items, hasMore}; an item
        has price, claimsCount, subscribeCounts, subscribeDays but no discount
        (OF's page derives it from the subscribe price, module 391477)."""
        params: dict[str, Any] = {"offset": offset}
        params.update(self._date_range_params(start, end))
        params["limit"] = limit
        return self.get_json(f"{API_BASE}/promotions", params=params)

    def trials_stats(self, *, start: str | None = None, end: str | None = None,
                     limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/trials/stats — Reach › Free trial links table. Response {items, hasMore}."""
        params: dict[str, Any] = {"offset": offset}
        params.update(self._date_range_params(start, end))
        params["limit"] = limit
        return self.get_json(f"{API_BASE}/trials/stats", params=params)

    def campaigns_stats(self, *, start: str | None = None, end: str | None = None,
                        limit: int = 10, offset: int = 0, field: str | None = None,
                        sort: str | None = None) -> dict:
        """GET /api2/v2/campaigns with OF's Reach › Tracking links query
        (module 616150 `A` via the campaigns store): limit, offset, pagination=1,
        startDate, endDate, with_deleted=1, sorting_deleted=0, stats=true, and
        field/sort for a column sort. Response {list:[campaign], hasMore};
        rows carry campaignName, campaignCode, createdAt, endDate,
        countTransitions, countSubscribers."""
        params: dict[str, Any] = {"limit": limit, "offset": offset, "pagination": 1}
        if field: params["field"] = field
        params.update(self._date_range_params(start, end))
        params.update({"with_deleted": 1, "sorting_deleted": 0, "stats": "true"})
        if sort: params["sort"] = sort
        return self.get_json(f"{API_BASE}/campaigns", params=params)

    # ── Statistics charts and per-item lists (module 977600, 616150) ──

    def _amount_count_chart(self, path: str, start, end, with_total: Any = "true") -> dict:
        """The Statements charts OF reads as {total, delta, chartAmount, chartCount}:
        withTotal, withChart=true, filter[chartAmount], filter[chartCount]."""
        params = self._date_range_params(start, end)
        params.update({"withTotal": with_total, "withChart": "true"})
        params.update(self._filter_params(["chartAmount", "chartCount"]))
        return self.get_json(f"{API_BASE}{path}", params=params)

    def payouts_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/payouts/chart — Statements › Payout requests chart."""
        return self._amount_count_chart("/payouts/chart", start, end)

    def referrals_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/payouts/referrals/chart — Statements › Referrals chart
        (OF sends withTotal=1 here, `true` on the other two)."""
        return self._amount_count_chart("/payouts/referrals/chart", start, end, with_total=1)

    def chargebacks_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/payouts/chargebacks/chart — Statements › Chargebacks chart."""
        return self._amount_count_chart("/payouts/chargebacks/chart", start, end)

    def promotions_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/promotions/chart?startDate&endDate&stats=1 — Reach › Promotions.
        Reply {claims, offers}, each {chart, total, delta}."""
        params = self._date_range_params(start, end)
        params["stats"] = 1
        return self.get_json(f"{API_BASE}/promotions/chart", params=params)

    def trials_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/trials/chart?startDate&endDate&stats=1 — Reach › Free trial
        links. Reply {claims, offers}, each {chart, total, delta}, as promotions."""
        params = self._date_range_params(start, end)
        params["stats"] = 1
        return self.get_json(f"{API_BASE}/trials/chart", params=params)

    def campaigns_chart(self, *, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/campaigns/chart — Reach › Tracking links: filter[clicks],
        filter[claims] (OF's defaults), startDate, endDate. Reply {clicks:
        [{date, count}], claims: [{date, count}], total, delta}: bare lists."""
        params = self._filter_params(["clicks", "claims"])
        params.update(self._date_range_params(start, end))
        return self.get_json(f"{API_BASE}/campaigns/chart", params=params)

    def stories_chart(self, *, by: str, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/stories/chart — Engagement › Stories: withTotal,
        filter[{by}], filter[stories]. Read as {<series>: {chart, total, delta}}."""
        params = self._date_range_params(start, end)
        params["withTotal"] = "true"
        params.update(self._filter_params([by, "stories"]))
        return self.get_json(f"{API_BASE}/stories/chart", params=params)

    def streams_chart(self, *, by: str, start: str | None = None, end: str | None = None) -> dict:
        """GET /api2/v2/streams/chart — Engagement › Streaming: withTotal,
        filter[{by}], filter[duration]."""
        params = self._date_range_params(start, end)
        params["withTotal"] = "true"
        params.update(self._filter_params([by, "duration"]))
        return self.get_json(f"{API_BASE}/streams/chart", params=params)

    def stream_viewers(self, stream_id: int, *, limit: int = 10, offset: int = 0,
                       tips_only: bool = False) -> dict:
        """GET /api2/v2/streams/{id}/viewers — the stream stats popup's Viewers
        (and, tips_only, Tippers) list: withFinishedViewers, onlyCurrentStreamTips
        [, onlyWithTips], limit, offset. Response {list:[user], hasMore?}."""
        params: dict[str, Any] = {"withFinishedViewers": "true", "onlyCurrentStreamTips": "true"}
        if tips_only: params["onlyWithTips"] = "true"
        params.update({"limit": limit, "offset": offset})
        return self.get_json(f"{API_BASE}/streams/{stream_id}/viewers", params=params)

    def story_viewers(self, story_id: int, *, limit: int = 10, offset: int = 0,
                      tips_only: bool = False) -> dict:
        """GET /api2/v2/stories/{id}/viewers — the story stats popup's Viewers
        (and, tips_only, Tippers: onlyWithTips) list. Response {list:[user], hasMore?}."""
        params: dict[str, Any] = {"onlyWithTips": "true"} if tips_only else {}
        params.update({"limit": limit, "offset": offset})
        return self.get_json(f"{API_BASE}/stories/{story_id}/viewers", params=params)

    # The Full stat / per-item stats popup header (module 977600 `q` and `j`,
    # 565144 `V`): one GET per item, withChart=true. OF reads the post's as
    # {lookCount, uniqueLookCount, likeCount, commentCount, tipCount, tipSum,
    # purchasedCount, purchasedSumm, lookDuration, lookDurationAverage, *All, *Chart}
    # (977600 setPostStat), the story's as {storyLookCount, storyLikeCount,
    # storyCommentCount, storyTipCount, storyTipSum, lookAll, story*All, story*Chart}
    # (setStoryStat), the stream's as {stream_look_count, stream_like_count,
    # stream_comment_count, stream_tip_count, stream_tip_sum, stream_duration,
    # stream_*_all, stream_*_chart} (263601 prepareStatsData).

    def post_stats(self, post_id: int) -> dict:
        """GET /api2/v2/posts/{id}/stats?withChart=true."""
        return self.get_json(f"{API_BASE}/posts/{post_id}/stats", params={"withChart": "true"})

    def post_users(self, post_id: int, kind: str, *, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/posts/{id}/buyers | /tips | /favorites?limit&offset — the
        buyer, tipper and liker lists a post's Purchases, Tips and Likes figures
        open (module 458723 `R`, `A` and `I`; the user-list modal pages them by
        10). {list:[user], hasMore}."""
        if kind not in ("buyers", "tips", "favorites"):
            raise ValueError(f"post user list must be buyers, tips or favorites, not {kind!r}")
        return self.get_json(f"{API_BASE}/posts/{post_id}/{kind}",
                             params={"limit": limit, "offset": offset})

    def offer_claims(self, offer_id: int, kind: str, *, limit: int = 10, offset: int = 0) -> dict:
        """Reach › Promotions / Free trial links "claimed" list (module 977600
        `le`): GET /api2/v2/subscriptions/subscribers?limit&offset&format=infinite
        &filter[promoId]=<id> (a promotion) or filter[trial_id]=<id> (a trial
        link). {list:[user], hasMore}. CONFIRMED live for both filters
        (2026-10-18, .scratch/growth-todo/capture.md): each user's
        subscribedOnData carries subscribeAt and totalSumm = subscribesSumm +
        postsSumm + messagesSumm + streamsSumm + tipsSumm (dollars), on
        promotion claimers as on trial ones. OF reads at most 20 rows per call:
        a limit above 20 with offset += limit silently skips fans (limit 50
        returned 44 of 96), so callers walk at <= 20. Pages run short of the
        limit mid-list, and hasMore is unreliable both ways (true on an empty
        page, true on a short last page)."""
        key = {"promo": "promoId", "trial": "trial_id"}.get(kind)
        if key is None:
            raise ValueError(f"offer kind must be promo or trial, not {kind!r}")
        return self.get_json(f"{API_BASE}/subscriptions/subscribers",
                             params={"limit": limit, "offset": offset, "format": "infinite",
                                     f"filter[{key}]": offer_id})

    def campaign_claimers(self, campaign_id: int, *, limit: int = 10, offset: int = 0,
                          query: str | None = None) -> dict:
        """Reach › Tracking links subscribers list: GET /api2/v2/campaigns/{id}/claimers
        (module 616150 `_`, via the campaigns store's fetchCampaignClaimers). OF's
        user-list modal sends more=false on the first page and more=true on each
        next one (offset > 0), then limit, offset and, when typed, query.
        {list:[user], hasMore}."""
        params: dict[str, Any] = {"more": "true" if offset else "false", "limit": limit, "offset": offset}
        if query: params["query"] = query
        return self.get_json(f"{API_BASE}/campaigns/{campaign_id}/claimers", params=params)

    def payout_invoice(self, invoice_id: int, *, referral: bool = False):
        """GET /api2/v2/payouts/download-approved-invoice?invoiceId&app-token&isRefbonus
        — an approved payout request's invoice (module 887384; OF's page opens it
        in a new tab, isRefbonus=1 on the referral payouts list). Returns the raw
        response: the caller streams its bytes and must not log its URL (a
        redirect may have landed on a signed CDN URL)."""
        return self.get(f"{API_BASE}/payouts/download-approved-invoice",
                        params={"invoiceId": invoice_id, "app-token": APP_TOKEN,
                                "isRefbonus": 1 if referral else 0})

    def referrals(self, *, start: str | None = None, end: str | None = None,
                  offset: int = 0, marker: str | None = None,
                  only_performers: bool = False) -> dict:
        """GET /api2/v2/users/me/referrals — Statements › Referrals ›
        Referred creators (onlyPerformers=1) / Referred users (onlyPerformers=0).
        OF sends startDate, endDate, offset, marker, onlyPerformers (no limit).
        Response {list:[user + earnings, joinDate], marker, hasMore}."""
        params = self._date_range_params(start, end)
        params["offset"] = offset
        if marker: params["marker"] = marker
        params["onlyPerformers"] = 1 if only_performers else 0
        return self.get_json(f"{API_BASE}/users/me/referrals", params=params)

    # ── Bookmarks (the OF "Collections > Bookmarks" tab) ───────

    def bookmarks_all(self, *, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/posts/bookmarks/all/ — paginated bookmarks feed."""
        return self.get_json(f"{API_BASE}/posts/bookmarks/all/",
                             params={"format": "infinite", "limit": limit, "offset": offset, "skip_users": "all"})

    # ── Referrals (creator referral program) ───────────────────

    def referrals_balance(self) -> dict:
        """GET /api2/v2/payments/referrals/balance — referral earnings balance."""
        return self.get_json(f"{API_BASE}/payments/referrals/balance")

    def referral_payouts(self, *, limit: int = 10, offset: int = 0, start: str | None = None,
                         end: str | None = None, marker: str | None = None) -> dict:
        """GET /api2/v2/payouts/requests/referral — referral payout history, paged
        as /payouts/requests (app.js 977600 `re`)."""
        return self.get_json(f"{API_BASE}/payouts/requests/referral",
                             params=self._payout_list_params(limit, offset, start, end, marker))

    # ── Notification settings ──────────────────────────────────

    def notification_settings(self, transport: str, *, group: int | None = None) -> list:
        """GET /api2/v2/users/settings/notifications/{transport} — per-transport
        toggles, grouped lists of `{code, isEnabled, ...}` with `group=1`."""
        params = {"group": group} if group is not None else None
        return self.get_json(f"{API_BASE}/users/settings/notifications/{transport}", params=params)

    # ── GIF picker (OF proxies Giphy under /giphy/proxy/...) ───
    # Discovered live by clicking the chat-compose "Add GIF" icon.

    def gif_trending(self, *, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/giphy/proxy/gifs/trending — trending GIFs (Giphy via OF)."""
        return self.get_json(f"{API_BASE}/giphy/proxy/gifs/trending",
                             params={"limit": limit, "offset": offset})

    def gif_search(self, query: str, *, limit: int = 10, offset: int = 0) -> dict:
        """GET /api2/v2/giphy/proxy/gifs/search?q=cat — search Giphy via OF's proxy."""
        return self.get_json(f"{API_BASE}/giphy/proxy/gifs/search",
                             params={"q": query, "limit": limit, "offset": offset})

    # ── Message templates (welcome message + saved replies) ────
    # Captured live — the
    # /my/settings/messaging page fires GET /messages/templates which
    # returns saved replies + the welcome message (template name
    # "reply_on_subscribe"). Each entry has full media + price.

    def message_templates(self, *, template: str | None = None) -> list:
        """GET /api2/v2/messages/templates — saved replies + welcome message.
        Pass `template='reply_on_subscribe'` to filter to the welcome message."""
        params: dict[str, Any] = {}
        if template:
            params["template"] = template
        return self.get_json(f"{API_BASE}/messages/templates",
                             params=params or None)

    # ── Subscription bundles ──────────────────────────────────

    def subscription_bundles(self) -> list:
        """GET /api2/v2/subscriptions/bundles — multi-month bundle pricing."""
        return self.get_json(f"{API_BASE}/subscriptions/bundles")

    # ── Tracking links (subscription analytics) ───────────────
    # GET /campaigns lists every tracking link with countSubscribers /
    # countTransitions. Captured live from
    # /my/settings/subscription/tracking-links.

    def tracking_links(self, *, limit: int | None = None, offset: int = 0,
                       with_deleted: bool = False) -> Any:
        """GET /api2/v2/campaigns — tracking link entries with lifetime
        transition + sub stats. Response {list:[campaign], hasMore}: the read
        pages, so a caller wanting every link loops `offset` while hasMore
        holds. `with_deleted` adds OF's own Reach flags (with_deleted=1,
        sorting_deleted=0) so deleted campaigns come back with isDeleted:true
        and their counts. No startDate/endDate: the counts stay all-time.
        Bare (no args) is the original unpaged read."""
        params: dict[str, Any] = {}
        if limit is not None:
            params.update({"limit": limit, "offset": offset, "pagination": 1})
        if with_deleted:
            params.update({"with_deleted": 1, "sorting_deleted": 0})
        return self.get_json(f"{API_BASE}/campaigns", params=params or None)

    # ── Free-trial links ──────────────────────────────────────
    # GET /trials returns active trial-link entries; each has a public URL,
    # subscribeDays (free duration), subscribeCounts (cap), claimCounts.

    def trial_links(self, *, offset: int = 0, limit: int = 100) -> list:
        """GET /api2/v2/trials — free-trial link list with usage counts.

        PAGINATED, and the default page is only THREE items. Verified live
        2026-07-22 (Ava): a bare call returned 3 of 18 links; limit=50 and
        limit=100 both returned all 18. A bare call silently hides most of the
        creator's links.
        """
        return self.get_json(f"{API_BASE}/trials",
                             params={"offset": int(offset), "limit": int(limit)})

    def trial_links_sorted(self, *, offset: int = 0, limit: int = 100,
                           field: str | None = None, sort: str | None = None) -> Any:
        """GET /api2/v2/trials with OF's own sort menu (TrialFilter, build
        202610091632): `field` create_date | expire_date | subscribe_counts |
        subscribe_days | claims_count | clicks_count | shared, `sort` asc | desc;
        OF sends neither for its default (create_date, desc)."""
        params: dict[str, Any] = {"limit": int(limit), "offset": int(offset), "pagination": 1}
        if field and sort:
            params["field"] = field
            params["sort"] = sort
        return self.get_json(f"{API_BASE}/trials", params=params)

    def trials_shared_with_me(self, *, offset: int = 0, limit: int = 100) -> Any:
        """GET /api2/v2/trials/share-access — the "Shared with you" tab
        (subscribers/fetchSharedTrials)."""
        return self.get_json(f"{API_BASE}/trials/share-access",
                             params={"limit": int(limit), "offset": int(offset), "pagination": 1})


# Last, not first: of_client imports this module while it loads, and these
# names are read only when a method runs, so either import order works.
from of_client import (  # noqa: E402
    API_BASE, APP_TOKEN, CHAT_MEDIA_KINDS, OFAPIError, OFDeniedError, log_of,
)
