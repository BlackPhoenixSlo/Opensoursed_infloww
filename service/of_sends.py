"""OFClient's writes: messages, mass/scheduled messages, posts, stories, chat and
user actions, settings, promos, lists, and the co-performer tag block every
media send goes through. One part of `of_client.OFClient`."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class SendsMixin:
    """Needs `_Transport` (`post_json`, `put_json`, `delete_json`, `request_json`,
    `_proxy_retry`, `http`, `user_id`, `timeout_s`); calls UploadMixin
    `upload_media`."""

    # ── Co-performer auto-tag ───────────────────────────────────
    # OF's release-form rule: media showing anyone besides the account owner
    # must name that person. Enforced here rather than at the ~20 senders that
    # attach media, because a sender added later would forget — every body
    # below that carries vault media ids goes through these two helpers and
    # of_client's module-level `_write_tag_block`.
    # See service/media_cotag.py for the solo/not-solo decision.
    #
    # WHERE the tag rides: `rfTag`, never `userTags`. The string `userTags`
    # appears in ZERO of the 268 captured OF chunks — OF's own client never
    # emits it. Every composer marshals the picks into the release-form arrays
    # (chunk 14562): {rfTag: picks type=="user", rfGuest: …, rfPartner: …},
    # which is the `partnerSource: "tag"` shape that comes back on a message's
    # `releaseForms`. Proven for the 1:1 chat body 2026-08-16 (two sends with
    # valid `userTags` → 200, `releaseForms: []`), and `rfTag` was added there —
    # but ONLY there, on the theory that `/messages/queue` honoured `userTags`.
    # It does not: across August 2026, 1,903 mass `ppv_send` messages with
    # intact `raw_json` stored `releaseForms: []`, every single one, while the
    # 1:1 lane landed its tags. (The two 2026-08-14 queue sends that looked
    # tagged carried TWO ids where `cotags_for` returns exactly one — OF's own
    # media-level forms, not ours.) So the arrays go on every body that tags.
    # `userTags` stays: it costs nothing, and dropping a field OF has tolerated
    # for months is a second change with no evidence behind it.

    def _apply_cotags(self, body: dict, media_files, tagged_users,
                      auto_tag: bool) -> _CoTagRetry | None:
        """Decide WHO this body tags and write the block. Returns the retry plan.

        Owns the decision — whose ids, the int coercion, the "operator first"
        order — while `_write_tag_block` owns the fields, so the five bodies
        below state neither. An operator's explicit picks always survive; the
        auto tag is appended, never substituted. Any failure degrades to "send
        what the caller asked for": resolving a tag must not be able to block a
        send.

        `None` back means we added nobody, so a 4xx has nothing to retry away.
        Otherwise the plan carries the operator's ids rather than a bare "we
        added one" — both sources share a single array, and a boolean left the
        retry unable to strip selectively, so it blanked a human's pick along
        with ours. It is a LOCAL for the caller to hand to
        `_post_dropping_auto_cotag`, deliberately not instance state — one
        OFClient is shared across accounts' concurrent `to_thread` sends
        (client_pool), so anything remembered on `self` would be a data race.
        """
        explicit = [int(u) for u in (tagged_users or [])]
        extra: list[int] = []
        if auto_tag:
            try:
                import media_cotag
                extra = [u for u in media_cotag.cotags_for(self, media_files)
                         if u not in explicit]
            except Exception:
                log_of.exception("co-performer tag resolution failed — sending as-is")
        # Read before the write, and write unconditionally: with no ids the
        # block is a no-op on every body here (nothing sets `userTags` itself,
        # and a native `rfTag` is already `[]`), so the untagged path needs no
        # branch of its own.
        native_rf = "rfTag" in body
        _write_tag_block(body, explicit + extra, native_rf=native_rf)
        return _CoTagRetry(explicit, native_rf) if extra else None

    def _post_dropping_auto_cotag(self, path: str, body: dict,
                                  retry_plan: _CoTagRetry | None):
        """POST, and if OF refuses a body we auto-tagged, retry with OUR id gone.

        OF 400s the entire send on a tag id it does not accept, so an auto-tag
        that goes stale (the tag request revoked, say) would otherwise take down
        every media send on the account. Any 4xx is treated as possibly-the-tag:
        the retry costs one request, and if the real cause was something else the
        retry surfaces it unchanged. Logged at ERROR because an untagged
        multi-person send is exactly what this feature exists to prevent — it
        should be visible, not silently absorbed.

        `retry_plan` is None when we added nobody — then any error is the
        caller's and raises untouched. Otherwise the retry REWRITES the block
        from the operator's own picks through the same `_write_tag_block` that
        built it, so the two directions cannot drift: an undo that blanked what
        it had never set is how a human's explicit release-form pick once got
        dropped behind a 200. If OF refuses that second body too it raises — an
        operator's own rejected pick is a real error and has to surface
        (test_media_cotag.py).
        """
        try:
            return self.post_json(path, json_body=body)
        except OFAPIError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if retry_plan is None or status not in (400, 422):
                raise
            log_of.error(
                "OF rejected %s with auto co-tag userTags=%r rfTag=%r (%s) — "
                "RESENDING with operator picks %r only: %s",
                path, body.get("userTags"), body.get("rfTag"), status,
                retry_plan.keep, str(exc).splitlines()[0][:200],
            )
            # Forget the id OF just refused, or the resolver keeps serving it
            # for the rest of its TTL and every send pays POST → 400 → POST.
            try:
                import media_cotag
                media_cotag.forget_tag_id(getattr(self, "account_id", ""))
            except Exception:
                log_of.exception("could not invalidate the rejected co-tag id")
            # The same writer, one id list shorter — the operator's picks alone.
            retry = dict(body)
            _write_tag_block(retry, retry_plan.keep,
                             native_rf=retry_plan.native_rf)
            return self.post_json(path, json_body=retry)

    # ── Messages: write ─────────────────────────────────────────

    def send_message(self, chat_id: str | int, text: str, *,
                     locked_text: bool = False, price: int | float = 0,
                     media_files: list | None = None,
                     previews: list[int] | None = None,
                     is_forward: bool = False,
                     reply_to_message_id: int | None = None,
                     tagged_users: list[int] | None = None,
                     giphy_id: str | None = None,
                     rf_guest: list[int] | None = None,
                     rf_partner: list[int] | None = None,
                     auto_tag: bool = True) -> dict:
        """POST /api2/v2/chats/{chat_id}/messages — send a message to one fan
        (or another creator, when both subscribe to each other).

        `chat_id` is the *other user's* numeric id.
        `text` may be plain text or HTML; OF web always wraps plain text in
        `<p>…</p>` before posting, and creator-to-creator sends appear to
        REQUIRE this wrapping — pre-wrap here so the relay's behavior
        matches OF web exactly. (Verified live 2026-05-19: bidirectional
        send fails when fields are omitted, succeeds with this shape.)

        `price` > 0 means a PPV (locks media behind purchase); pair with
        `locked_text=True` to lock the text too. `media_files` are vault
        media IDs previously uploaded via /vault/media — leave empty for
        text-only.

        `reply_to_message_id` is OF's native quote-reply: setting it makes
        the receiving side render the original message as a card above
        this one (matches OF web's "↪ Reply" UX exactly).

        Returns the created message object (same shape as items in
        /chats/.../messages.list)."""
        text = _guard_outbound(text)
        body = self._message_body(
            text, locked_text=locked_text, price=price, media_files=media_files,
            previews=previews, is_forward=is_forward,
            reply_to_message_id=reply_to_message_id, giphy_id=giphy_id,
            rf_guest=rf_guest, rf_partner=rf_partner)
        # `userTags` is OF's "tag other creators in this message" field —
        # numeric user ids, captured from /self/tagged-friend-users. OF
        # rejects unknown / non-friend ids with 400, so the picker UI is
        # the contract: only ids it surfaces will succeed. Set before the log
        # below so the diagnostic reports what OF actually receives.
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        # Diagnostic — confirms OF receives the previews subset we expect.
        # OF silently ignores previews on free messages, so price=0 + a
        # non-empty previews list is also worth flagging.
        # `rfTag` is logged beside `userTags` because it is the field that
        # actually tags this endpoint — without it the log cannot answer "did
        # the tag go out?", which is the exact question that took a live probe
        # of OF's stored `releaseForms` to settle on 2026-08-16.
        log_of.info(
            "send_message chat=%s price=%s mediaFiles=%r previews=%r "
            "userTags=%r rfTag=%r giphyId=%r",
            chat_id, price, body["mediaFiles"], body["previews"],
            body.get("userTags") or [], body.get("rfTag") or [],
            body.get("giphyId"),
        )
        # Every DM's one way out: count it in the account's DM window
        # (dm_rate, ADR 0025): the peak, an automation DM sent without its
        # turn, the operator's sends that automation leaves room for.
        import dm_rate
        dm_rate.record(getattr(self, "account_id", None))
        return self._post_dropping_auto_cotag(
            f"{API_BASE}/chats/{chat_id}/messages", body, retry_plan)

    @staticmethod
    def _message_body(text: str, *, locked_text: bool,
                      price: int | float, media_files: list | None,
                      previews: list[int] | None, is_forward: bool,
                      reply_to_message_id: int | None,
                      giphy_id: str | None,
                      rf_guest: list[int] | None,
                      rf_partner: list[int] | None) -> dict:
        """send_message's body before the tag block, from its already-guarded
        `text`: the one place its names become OF's keys (and their order).
        Every arg required: send_message owns the defaults."""
        # GIF sends pass an empty text — OF stores the GIF reference under
        # the top-level `giphyId` field, not in `mediaFiles`. Skip the <p>
        # wrap so the empty string survives literally (OF echoes "text":""
        # back). Verified live 2026-05-23 via captured cURL.
        wrapped_text = "" if (giphy_id and not text) else _wrap_text_as_p(text)
        body = {
            "text": wrapped_text,
            "lockedText": locked_text,
            "mediaFiles": media_files or [],
            "price": price,
            # `previews` is plural — list of vault media ids that ride along
            # as UNLOCKED teasers when `price > 0`. Empty list = everything
            # locked. Verified live on OF web 2026-05-23: sending 3 mediaFiles
            # + price=5 + previews=[id1] yields 1 free thumb + 2 locked.
            "previews": previews or [],
            # Release-form consent fields. OF web always sends these as
            # empty arrays; omitting them seems to be why creator-to-
            # creator sends 400 "Cannot send message to this user".
            "rfTag": [],
            # A guest (`rfGuest`) and a release form's link or document
            # (`rfPartner`) tagged in the composer, as OF web's mapper sends
            # them; send_message's tag block (`_write_tag_block`) keeps them
            # (setdefault).
            "rfGuest": [int(i) for i in (rf_guest or [])],
            "rfPartner": [int(i) for i in (rf_partner or [])],
            "isForward": is_forward,
        }
        if giphy_id:
            # Sibling of mediaFiles, not nested inside it. OF echoes it on
            # the response object (`"giphyId":"…","mediaCount":0`). One per
            # send — desktop OF doesn't let you attach multiple GIFs.
            body["giphyId"] = str(giphy_id)
        if reply_to_message_id is not None:
            body["replyToMessageId"] = reply_to_message_id
        return body

    # ── Chat message-level writes — VERIFIED LIVE ──────────────
    # All four paths are under /messages/{id}/..., NOT /chats/{cid}/messages/{mid}/...
    # as OFAuth's docs imply. Confirmed by running each against chat 117183 on
    # my own test account (see CHANGES.md section "verified writes").

    def unsend_message(self, message_id: int, with_user_id: int | None = None) -> Any:
        """DELETE /api2/v2/messages/{message_id} — unsend a chat message.
        DESTRUCTIVE: only works inside OF's edit window (~24h).

        OF web sends `{"withUserId": <fan_id>}` in the request body. The
        endpoint accepts an empty body too (legacy callsites), but for
        mass-message bubbles the response only includes the `queue` block
        when withUserId is passed — without it the response is
        `{"success": true}` with no way to discover the parent queue id,
        so callers that may want to follow up with an "unsend from all"
        should always pass it."""
        body: dict | None = {"withUserId": int(with_user_id)} if with_user_id is not None else None
        return self.delete_json(f"{API_BASE}/messages/{message_id}", json_body=body)

    def like_message(self, message_id: int) -> Any:
        """POST /api2/v2/messages/{message_id}/like → {success, isLiked: true}.
        VERIFIED LIVE. You can only like the OTHER party's messages (liking
        your own returns 404 'Message not found')."""
        return self.post_json(f"{API_BASE}/messages/{message_id}/like")

    def unlike_message(self, message_id: int) -> Any:
        """DELETE /api2/v2/messages/{message_id}/like → {success, isLiked: false}.
        VERIFIED LIVE."""
        return self.delete_json(f"{API_BASE}/messages/{message_id}/like")

    def pin_message(self, message_id: int, user_id: int | str) -> Any:
        """POST /api2/v2/messages/{message_id}/pin/user/{user_id} → {success: true}.

        ⚠️ THIS IS A TOGGLE, NOT AN ADD. Calling it on a message that is ALREADY
        pinned UNPINS it — and still answers `{"success": true}`, so the response
        cannot tell you which of the two things just happened. Probed live
        2026-07-27 on a throwaway thread: pin → present, pin again → GONE, pin a
        third time → back.

        The consequence for any caller: "pin this" without first knowing whether
        it is already pinned can silently DESTROY a pin while reporting success.
        Check the chat's pinned list (`get_pinned_messages`) first and only call
        this when the id is absent from it. (The retired `automations/_pins`
        did exactly that, and found this behaviour the hard way.)

        OF's web client uses the longer `/pin/user/{user_id}` form which scopes
        the pin to the chat partner. The shorter `/pin` form also returns 200
        but doesn't reliably make the message appear in the chat's pinned list.
        Captured curl 2026-05-20 confirms the long path is what the live UI
        sends."""
        return self.post_json(f"{API_BASE}/messages/{message_id}/pin/user/{user_id}")

    def unpin_message(self, message_id: int, user_id: int | str) -> Any:
        """DELETE /api2/v2/messages/{message_id}/pin/user/{user_id} → {success: true}.
        Mirrors pin_message — same path, DELETE method."""
        return self.delete_json(f"{API_BASE}/messages/{message_id}/pin/user/{user_id}")

    def unpin_all_messages(self, chat_id: str | int) -> Any:
        """DELETE /api2/v2/chats/{chat_id}/messages/pin — OF web's pinned page
        "Unpin all messages" (chats API 204607 `k`)."""
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/messages/pin")

    def hide_message(self, message_id: int, with_user_id: int) -> Any:
        """PUT /api2/v2/messages/{message_id}/hide {"withUserId": <fan>} — OF web's
        per-message "Hide" on a message the other side sent (204607 `M`)."""
        return self.put_json(f"{API_BASE}/messages/{message_id}/hide",
                             json_body={"withUserId": int(with_user_id)})

    def bookmark_message(self, message_id: int, chat_group_id: int | None, on: bool) -> Any:
        """POST|DELETE /api2/v2/posts/{message_id}/bookmarks {"chat_group_id": <queueId>} —
        OF web's per-message Bookmark / Unbookmark (posts API 458723 `P`/`w`: a
        message is bookmarked through the posts route, its chat group named)."""
        body = {"chat_group_id": chat_group_id} if chat_group_id is not None else None
        if on:
            return self.post_json(f"{API_BASE}/posts/{message_id}/bookmarks", json_body=body)
        return self.delete_json(f"{API_BASE}/posts/{message_id}/bookmarks", json_body=body)

    # ── Chat-level actions (VERIFIED LIVE) ─────────────────────
    # Found via the OnlyFansAPI public catalog. The OF endpoints follow a
    # consistent POST-to-do / DELETE-to-undo pattern.

    def mark_chat_read(self, chat_id: str | int) -> Any:
        """POST /api2/v2/chats/{chat_id}/mark-as-read → {success:true}."""
        return self.post_json(f"{API_BASE}/chats/{chat_id}/mark-as-read")

    def mark_chat_unread(self, chat_id: str | int) -> Any:
        """DELETE /api2/v2/chats/{chat_id}/mark-as-read → {success:true}.
        Same path as mark-read but DELETE — OF's symmetric undo convention."""
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/mark-as-read")

    def mark_all_chats_read(self) -> Any:
        """POST /api2/v2/chats/mark-as-read → {success:true}. Marks every chat as read."""
        return self.post_json(f"{API_BASE}/chats/mark-as-read")

    def mute_chat(self, chat_id: str | int) -> Any:
        """POST /api2/v2/chats/{chat_id}/mute."""
        return self.post_json(f"{API_BASE}/chats/{chat_id}/mute")

    def unmute_chat(self, chat_id: str | int) -> Any:
        """DELETE /api2/v2/chats/{chat_id}/mute."""
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/mute")

    def hide_chat(self, chat_id: str | int) -> Any:
        """POST /api2/v2/chats/{chat_id}/hide — removes from the inbox view.
        The chat still exists; the fan can still message you."""
        return self.post_json(f"{API_BASE}/chats/{chat_id}/hide")

    def unhide_chat(self, chat_id: str | int) -> Any:
        """DELETE /api2/v2/chats/{chat_id}/hide."""
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/hide")

    def delete_chat(self, chat_id: str | int) -> Any:
        """DELETE /api2/v2/chats/{chat_id}: OF web's chat-list row "x" (Clear messages,
        `deleteChat` in its chats store; its bulk form joins ids with commas). Clears the
        chat's messages on the Creator's side and drops it from the inbox. Not reversible."""
        return self.delete_json(f"{API_BASE}/chats/{chat_id}")

    # ── User-level moderation: block + restrict ────────────────
    # block: hides the chat AND blocks them from messaging you
    # restrict: hides their public profile content from you (you still see chat)
    # Both undo with DELETE on the same path.

    def block_user(self, user_id: str | int) -> Any:
        """POST /api2/v2/users/{user_id}/block. VERIFIED LIVE."""
        return self.post_json(f"{API_BASE}/users/{user_id}/block")

    def unblock_user(self, user_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/users/{user_id}/block")

    def restrict_user(self, user_id: str | int) -> Any:
        """POST /api2/v2/users/{user_id}/restrict. VERIFIED LIVE."""
        return self.post_json(f"{API_BASE}/users/{user_id}/restrict")

    def unrestrict_user(self, user_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/users/{user_id}/restrict")

    # ── Follow / subscribe (creator → fan re-engagement) ──────
    # Endpoints read straight out of OnlyFans' own web bundle (app.js), NOT
    # guessed:
    #   T = (e,t={}) => post(`/users/${e}/subscribe`, t)
    #   E = (e,t={}) => post(`/users/${e}/resubscribe`, t)
    #   P = (e,{reasonId}) => delete(`/users/${e}/subscribe`, {data:{reason}})
    #
    # ⚠️ MONEY: "subscribe" is OnlyFans' pay-to-subscribe action. It is free
    # ONLY when the target's subscribePrice is 0 (a free profile). Following a
    # fan whose profile is paid would CHARGE the creator. Callers MUST verify
    # subscribePrice == 0 before calling follow_user — this method does not, and
    # cannot, know the price.
    #
    # VERIFIED LIVE 2026-07-23 on the owned Ava→founder loop (free profile):
    # unfollow(reason=1) → subscribe re-follow works end-to-end, restores the
    # edge with a FRESH expire clock, and OF RE-SENDS the "started following
    # you" notification (seen on the target account within the minute).

    def follow_user(self, user_id: str | int) -> Any:
        """POST /api2/v2/users/{id}/subscribe — follow/subscribe to a user.
        FREE only when their subscribePrice == 0; otherwise it PAYS. Gate first."""
        return self.post_json(f"{API_BASE}/users/{user_id}/subscribe", json_body={})

    def unfollow_user(self, user_id: str | int, *, reason_id: int = 1) -> Any:
        """DELETE /api2/v2/users/{id}/subscribe — unfollow/unsubscribe.
        `reason` is REQUIRED: an empty body 400s ("Invalid reason"); reason=1
        is accepted. VERIFIED LIVE 2026-07-23 (Ava→founder)."""
        return self.delete_json(f"{API_BASE}/users/{user_id}/subscribe",
                                json_body={"reason": reason_id})

    def resubscribe_user(self, user_id: str | int) -> Any:
        """POST /api2/v2/users/{id}/resubscribe — re-follow a LAPSED/EXPIRED
        relationship. NOT for a just-unfollowed one: there it 400s
        ("Resubscribe failed.") and the re-follow must go through
        /subscribe instead. VERIFIED LIVE 2026-07-23 (Ava→founder)."""
        return self.post_json(f"{API_BASE}/users/{user_id}/resubscribe", json_body={})

    def add_link_claimers_to_list(self, list_id: str | int, kind: str, link_id: int) -> Any:
        """OF's "Add to list" on a link's claimers: every fan the link lists
        now goes into the list in one call, no body. A tracking link:
        POST /api2/v2/lists/{list_id}/users/campaign/{id}/claimers, CONFIRMED
        live 2026-10-18 from OF's own claimers modal: 200 {"count": n}, n the
        fans newly added; a repeat answers {"count": 0} (idempotent). A trial
        link or promotion: POST /lists/{list_id}/users/{trial|promo}/{id}/claims
        (OF's usersLists/addClaimsToList, module 138255), CONFIRMED live
        2026-10-19 for both (.scratch/growth-followup/capture.md): no body,
        200 {"count": n}, a repeat {"count": 0}."""
        lid = str(list_id)
        if not lid.isdigit():
            raise ValueError(f"list id must be a custom list's number, not {list_id!r}")
        if kind == "campaign":
            path = f"{API_BASE}/lists/{lid}/users/campaign/{int(link_id)}/claimers"
        elif kind in ("trial", "promo"):
            path = f"{API_BASE}/lists/{lid}/users/{kind}/{int(link_id)}/claims"
        else:
            raise ValueError(f"link kind must be campaign, trial or promo, not {kind!r}")
        return self.post_json(path)

    # ── Statistics › Fans row writes (module 616150, 138255) ──

    def set_subscription_discount(self, user_id: str | int, discount: int, period: int) -> Any:
        """PUT /api2/v2/subscriptions/{user_id}/discount {discount, period} — a
        fan's personal subscription discount, OF web's "Give user a discount"
        (its subscribers store putSubscriptionDiscount, module 616150 `S`; the
        Discount dialog, chunk 40681 module 424562, offers 5..60 % in steps of 5
        for 1..12 months; its "clear" sends discount 0, period 1). OF answers
        with the subscriber."""
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}/discount",
                             json_body={"discount": int(discount), "period": int(period)})

    # ── Welcome message (reply_on_subscribe) slot ─────────────
    # OF web doesn't address the welcome slot by numeric id — it POSTs/
    # DELETEs directly to /messages/templates/reply_on_subscribe and uses
    # an extended body shape (rfTag/rfGuest/rfPartner/previews/isForward).
    # The numeric-id PUT/DELETE on the generic template endpoint works
    # less reliably; using the slot URL is what the live UI does.
    #
    # Separately, the master "send welcome to new subs" flag lives on
    # /users/me as `replyOnSubscribe` (PATCH). The template stores text
    # + media; the flag controls whether OF actually fires it.

    def set_reply_on_subscribe(self, enabled: bool) -> Any:
        """PATCH /api2/v2/users/me with `{replyOnSubscribe: bool}` — the
        master switch for whether OF fires the welcome template on new
        subs. Independent from whether the template content exists."""
        return self.request_json(
            "PATCH", f"{API_BASE}/users/me",
            json_body={"replyOnSubscribe": bool(enabled)},
        )

    def create_bundle(self, *, months: int | None = None, price: float | None = None,
                      discount: int | None = None, duration: int | None = None) -> Any:
        """POST /api2/v2/subscriptions/bundles.

        `duration` (months) is OF's own composer shape: its ADD SUBSCRIPTION BUNDLE
        dialog (build 202610091632, `bundles/saveBundle`) sends exactly
        `{discount, duration}` and OF prices the bundle itself. Without `duration`
        the legacy `{months, price[, discount]}` body is sent (unverified)."""
        if duration is not None:
            body: dict[str, Any] = {"discount": int(discount or 0), "duration": int(duration)}
        else:
            body = {"months": months, "price": price}
            if discount is not None: body["discount"] = discount
        return self.post_json(f"{API_BASE}/subscriptions/bundles",
                              json_body=body)

    def delete_bundle(self, bundle_id: int) -> Any:
        """DELETE /api2/v2/subscriptions/bundles/{id}."""
        return self.delete_json(f"{API_BASE}/subscriptions/bundles/{bundle_id}")

    def edit_bundle(self, bundle_id: int, *, discount: int, duration: int) -> Any:
        """PUT /api2/v2/subscriptions/bundles/{id} — OF's own edit (build 202610091632,
        `bundles/saveBundle` with an id): body `{discount, duration, id}`, answered with
        the bundle. Read statically from OF's bundle, never sent live (OF's settings UI
        shows no Edit; this is for the live switch-and-restore check)."""
        return self.put_json(f"{API_BASE}/subscriptions/bundles/{bundle_id}",
                             json_body={"discount": int(discount), "duration": int(duration),
                                        "id": int(bundle_id)})

    # ── Promotion campaigns (write side) ──────────────────────
    # /promotions returns every promo type (all / expired / trial / offer)
    # in one paginated list. Writes follow OF's standard CRUD shape.

    def create_promo(self, *, subscribe_counts: int, subscribe_days: int = 30,
                     discount: int | None = None, message: str = "",
                     type: str | list[str] = "all", price: float | None = None,
                     finish_days: int | None = None) -> Any:
        """POST /api2/v2/promotions — create a subscription-DISCOUNT promo.

        VERIFIED LIVE 2026-07-22 (Ava): OF requires `discount` — an INTEGER
        PERCENT in [1, 100] off the current subscription price. `price` is NOT a
        valid field; sending it without `discount` 400s:
          {"errors":{"discount":["Discount is required","Discount must be an
           integer","Discount must be at least 1","Discount must be no more
           than 100"]}}
        `subscribe_counts` caps claims; `subscribe_days` is the discounted-access
        duration in days. The legacy `price=` kwarg is accepted but IGNORED
        (kept so old callers don't TypeError) — pass `discount`."""
        if discount is None:
            raise ValueError("create_promo requires discount (integer percent 1-100)")
        body: dict[str, Any] = {
            "discount": max(1, min(int(discount), 100)),
            "subscribeCounts": subscribe_counts,
            "subscribeDays": subscribe_days,
            "message": message, "type": type,
        }
        # OF's own Start campaign (ModalPromotion saveForm, build 202610091632)
        # also sends `finishDays` (the offer's expiration, 0 = none) and `type`
        # as a list (["all"], ["expired"] or both); a free trial is discount 100.
        if finish_days is not None:
            body["finishDays"] = int(finish_days)
        return self.post_json(f"{API_BASE}/promotions", json_body=body)

    def finish_promo(self, promo_id: int) -> Any:
        """POST /api2/v2/promotions/{id}/finish — Stop promotion (OF's
        `users/finishPromotion`, build 202610091632): ends a running campaign
        without deleting it (DELETE removes an ended one). No body, as OF's."""
        return self.post_json(f"{API_BASE}/promotions/{promo_id}/finish")

    def delete_promo(self, promo_id: int) -> Any:
        """DELETE /api2/v2/promotions/{id}."""
        return self.delete_json(f"{API_BASE}/promotions/{promo_id}")

    def create_tracking_link(self, *, name: str, code: int | None = None) -> Any:
        """POST /api2/v2/campaigns — register a new tracking link.

        The CREATE body field is `name` (verified live 2026-07-23: sending
        `campaignName` 400s "Name is required"). Note the asymmetry — the LIST
        response spells the same thing `campaignName`. `code` is the URL-suffix
        int; if omitted OF auto-picks the next available. VERIFIED LIVE."""
        body: dict[str, Any] = {"name": name}
        if code is not None:
            body["campaignCode"] = code
        return self.post_json(f"{API_BASE}/campaigns", json_body=body)

    def delete_tracking_link(self, campaign_id: int) -> Any:
        """DELETE /api2/v2/campaigns/{id}."""
        return self.delete_json(f"{API_BASE}/campaigns/{campaign_id}")

    def create_trial_link(self, *, name: str, subscribe_days: int = 7,
                          subscribe_counts: int = 1,
                          expired_at: str | None = None,
                          expire_days: int | None = None) -> Any:
        """POST /api2/v2/trials — issue a new free-trial link.
        `subscribe_days` is the free-access duration; `subscribe_counts` caps
        total claims (0 = no limit); `expired_at` ISO 8601 limits the link's
        validity window. `expire_days` is OF's own composer field: its "Create
        link" (ModalTrial saveForm, build 202610091632) sends exactly
        `{subscribeDays, subscribeCounts, expireDays, trialLinkName}`
        (expireDays 0 = no expiration)."""
        body: dict[str, Any] = {
            "trialLinkName": name,
            "subscribeDays": subscribe_days,
            "subscribeCounts": subscribe_counts,
        }
        if expire_days is not None:
            body["expireDays"] = int(expire_days)
        if expired_at:
            body["expiredAt"] = expired_at
        return self.post_json(f"{API_BASE}/trials", json_body=body)

    def share_trial_stats(self, *, trial_id: int, user_id: int) -> Any:
        """POST /api2/v2/trials/share-access {trialId, userId} — share a free
        trial link's statistics with another creator (the share dialog's Share)."""
        return self.post_json(f"{API_BASE}/trials/share-access",
                              json_body={"trialId": int(trial_id), "userId": int(user_id)})

    def delete_trial_link(self, trial_id: int) -> Any:
        """DELETE /api2/v2/trials/{id}."""
        return self.delete_json(f"{API_BASE}/trials/{trial_id}")

    # ── Profile writes (bio, display name, location, etc.) ────
    # Captured live via PATCH probe: PATCH /users/me accepts {about, name, …}
    # and returns {success:true}. Round-tripped on this account.

    def update_profile(self, **fields) -> Any:
        """PATCH /api2/v2/users/me — update profile fields.

        Verified fields (live): `about` (bio text). Other accepted keys
        likely include: name (display name), location, website, wishlist
        (URL), instagramUsername, twitterUsername, tiktokUsername — same
        names as the corresponding fields in /users/me response.
        """
        if not fields:
            raise ValueError("at least one field required")
        return self.request_json("PATCH", f"{API_BASE}/users/me", json_body=fields)

    # ── Settings writes (OF settings pages) ───────────────────
    # Shapes as OF's own web client sends them (build 202610091632, app.js
    # module 202600; per-key routing in settings-story.js module 289051).

    def patch_security_settings(self, fields: dict) -> Any:
        """PATCH /api2/v2/users/me/settings/security — one security-section
        toggle, `{key: value}` (OF's `users/patchUserMeBySection`)."""
        if not fields:
            raise ValueError("at least one field required")
        return self.request_json("PATCH", f"{API_BASE}/users/me/settings/security", json_body=fields)

    def put_security_settings(self, fields: dict) -> Any:
        """PUT /api2/v2/users/me/settings/security — OF's watermarks Save
        (`changeUserBySection`): `{hasWatermarkPhoto, hasWatermarkVideo,
        watermarkText?, watermarkPosition}`."""
        if not fields:
            raise ValueError("at least one field required")
        return self.request_json("PUT", f"{API_BASE}/users/me/settings/security", json_body=fields)

    def patch_notification_settings(self, body: dict) -> Any:
        """PATCH /api2/v2/users/settings/notifications — a notification toggle,
        `{notifications: {<transport>: [{code, value}]}}`, or an email master
        switch, `{isEmailNotificationsEnabled: bool, ...}`."""
        if not body:
            raise ValueError("empty body")
        return self.request_json("PATCH", f"{API_BASE}/users/settings/notifications", json_body=body)

    def patch_story_settings(self, allow_reply_from: str) -> Any:
        """PATCH /api2/v2/users/settings/story — `{allowReplyFrom}`
        ("subscribers" or "nobody" from OF's story replies switch)."""
        return self.request_json("PATCH", f"{API_BASE}/users/settings/story",
                                 json_body={"allowReplyFrom": allow_reply_from})

    # FAN NOTES + CUSTOM NAME: not native OF endpoints.
    # OnlyFansAPI exposes `PUT /fans/{id}/{notes,custom-name}` but these are
    # **their own service features** backed by their database, not proxied to OF.
    # Direct probing confirms no OF /api2/v2 path returns 200 for these.

    # ── Scheduled / mass messaging ─────────────────────────────

    def schedule_message(self, chat_id: str | int, text: str, *,
                         scheduled_date: str, price: int | float = 0,
                         locked_text: bool = False,
                         media_files: list[int] | None = None,
                         previews: list[int] | None = None,
                         tagged_users: list[int] | None = None,
                         auto_tag: bool = True) -> Any:
        """POST /api2/v2/messages/queue — schedule a message for future delivery.

        VERIFIED LIVE. The right path is `/messages/queue`, NOT
        `/chats/{id}/messages` with a scheduledDate field — the latter accepts
        the field but sends immediately (OF silently ignores it on that path).

        `scheduled_date` is ISO 8601 with timezone offset, e.g.
        '2026-06-01T18:00:00+00:00'. Returns the queue entry:
        `{id, date, isReady, isDone, total, pending, canUnsend, ...}`."""
        body = {
            "text": text,
            "lockedText": locked_text,
            "mediaFiles": media_files or [],
            "price": price,
            "previews": previews or [],
            "scheduledDate": scheduled_date,
            "userIds": [int(chat_id)],
        }
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        return self._post_dropping_auto_cotag(
            f"{API_BASE}/messages/queue", body, retry_plan)

    def schedule_mass_message(self, *, text: str, scheduled_date: str | None = None,
                              save_for_later: bool = False,
                              user_ids: list[int] | None = None,
                              user_lists: list[str | int] | None = None,
                              excluded_users: list[int] | None = None,
                              excluded_user_lists: list[str | int] | None = None,
                              price: int | float = 0,
                              locked_text: bool = False,
                              media_files: list[int] | None = None,
                              previews: list[int] | None = None,
                              tagged_users: list[int] | None = None,
                              giphy_id: str | None = None,
                              filters: dict | None = None,
                              online_only: bool = False,
                              auto_tag: bool = True) -> Any:
        """POST /api2/v2/messages/queue — schedule a MASS message (broadcast).
        Set `user_ids` to specific fans OR `user_lists` for built-in/custom lists
        (e.g. ['fans']). `excluded_user_lists` removes whole lists from the
        target set — the wire field is `excludedLists` (VERIFIED LIVE
        2026-06-12: a 1-fan list broadcast with the fan in an excludedLists
        list resolved to total=0; the old `excludeUserLists` name was
        silently ignored and the fan got the message).

        ⚠️ OF has NO per-user exclusion field on this endpoint —
        `excludedUsers` does not exist and was silently dropped for months.
        `excluded_users` here is honored CLIENT-SIDE only: those ids are
        subtracted from `user_ids` before the call. It cannot remove fans
        from a `user_lists`/online audience — sync such ids into an OF
        custom list and pass it via `excluded_user_lists` instead
        (see audiences.ensure_exclude_list).

        `giphy_id`: forwarded as top-level `giphyId` — matches the chat send
        wire shape. OF web includes GIFs on mass-message broadcasts; we
        mirror the field name and let OF accept/reject.

        `save_for_later` (no `scheduled_date`): OF's "Save for later", queued
        with no date: `isPublishedWithPeriod: 1`, as OF's message body builder
        sends it (`654685.Os`, build 202610091632). Not verified live."""
        if not scheduled_date and not save_for_later:
            raise ValueError("schedule_mass_message needs scheduled_date or save_for_later")
        body = self._mass_body(
            text=text, user_ids=user_ids, user_lists=user_lists,
            excluded_users=excluded_users, excluded_user_lists=excluded_user_lists,
            price=price, locked_text=locked_text, media_files=media_files,
            previews=previews, filters=filters, online_only=online_only)
        if scheduled_date:
            body["scheduledDate"] = scheduled_date
        else:
            body["isPublishedWithPeriod"] = 1
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        if giphy_id:
            body["giphyId"] = str(giphy_id)
        return self._post_dropping_auto_cotag(
            f"{API_BASE}/messages/queue", body, retry_plan)

    @staticmethod
    def _mass_body(*, text: str, user_ids, user_lists, excluded_users,
                   excluded_user_lists, price, locked_text, media_files,
                   previews, filters, online_only) -> dict:
        """The /messages/queue body both schedule_mass_message and
        edit_queued_message send (no date: each adds its own). `excluded_users`
        is subtracted from `userIds` here (OF has no per-user exclude field)."""
        excl_ids = {int(u) for u in (excluded_users or [])}
        body: dict = {
            "text": text,
            "lockedText": locked_text,
            "mediaFiles": media_files or [],
            "price": price,
            "previews": previews or [],
            "userIds": [int(u) for u in (user_ids or []) if int(u) not in excl_ids],
            "userLists": user_lists or [],
            "excludedLists": excluded_user_lists or [],
        }
        merged_filters = dict(filters) if filters else {}
        if online_only:
            merged_filters["online"] = 1
        if merged_filters:
            body["filters"] = merged_filters
        return body

    def edit_queued_message(self, queue_id: int, *, text: str,
                            scheduled_date: str | None = None,
                            save_for_later: bool = False,
                            user_ids: list[int] | None = None,
                            user_lists: list[str | int] | None = None,
                            excluded_user_lists: list[str | int] | None = None,
                            price: int | float = 0,
                            locked_text: bool = False,
                            media_files: list | None = None,
                            previews: list[int] | None = None,
                            tagged_users: list[int] | None = None) -> Any:
        """PUT /api2/v2/messages/queue/{queue_id} — save a queued mass message
        in place (OF's Edit message; `204607.y`, chats-send `sendScheduleMessage`
        with a loaded queue message), the same body as a new one: a new date
        is OF's reschedule. OF's body builder (`654685.Os`) sends `isScheduled: 1`
        with `scheduledDate`, and `isPublishedWithPeriod: 1` for saved for
        later. One of the two is required: a body with neither could send the
        message at once. Not verified live (no live write was made)."""
        if not scheduled_date and not save_for_later:
            raise ValueError("edit_queued_message needs scheduled_date or save_for_later")
        body = self._mass_body(
            text=text, user_ids=user_ids, user_lists=user_lists,
            excluded_users=None, excluded_user_lists=excluded_user_lists,
            price=price, locked_text=locked_text, media_files=media_files,
            previews=previews, filters=None, online_only=False)
        if scheduled_date:
            body["isScheduled"] = 1
            body["scheduledDate"] = scheduled_date
        else:
            body["isPublishedWithPeriod"] = 1
        self._apply_cotags(body, media_files, tagged_users, False)
        return self.put_json(f"{API_BASE}/messages/queue/{queue_id}", json_body=body)

    def cancel_scheduled(self, queue_id: int) -> Any:
        """DELETE /api2/v2/messages/queue/{queue_id} — cancel a scheduled send."""
        return self.delete_json(f"{API_BASE}/messages/queue/{queue_id}")

    def publish_schedule(self, schedule_id: int) -> Any:
        """PUT /api2/v2/schedules/{schedule_id}/publish — "Post now" / "Message now"
        on a queue item (scheduled or saved for later). No body; OF's web client
        (module 409363 `V9`) sends the schedule item's own `id`, not its entity's."""
        return self.put_json(f"{API_BASE}/schedules/{schedule_id}/publish")

    def send_mass_message(self, text: str, *,
                          user_lists: list[str | int] | None = None,
                          included_users: list[int] | None = None,
                          excluded_users: list[int] | None = None,
                          excluded_user_lists: list[str | int] | None = None,
                          price: int | float = 0,
                          locked_text: bool = False,
                          media_files: list[int] | None = None,
                          previews: list[int] | None = None,
                          scheduled_date: str | None = None,
                          tagged_users: list[int] | None = None,
                          giphy_id: str | None = None,
                          filters: dict | None = None,
                          online_only: bool = False,
                          auto_tag: bool = True) -> Any:
        """POST /api2/v2/messages/queue — broadcast to many fans at once.

        VERIFIED LIVE. Same endpoint as schedule_message — without scheduledDate
        it fires immediately. The old `/chats/messages` path is **404** on OF;
        I had it wrong. The right one is /messages/queue with `userLists`
        and/or `userIds` (note: NOT `includedUsers`) in the body.

        Targeting (combine as needed):
          - `user_lists`: built-in names ('fans', 'recent') or custom list ids
          - `included_users`: explicit fan ids
          - `excluded_users`: CLIENT-SIDE only — subtracted from
            `included_users` before the call. OF has NO per-user exclusion
            field on this endpoint (`excludedUsers` doesn't exist; VERIFIED
            LIVE 2026-06-12 — it was silently dropped and excluded fans got
            the blast). To exclude ids from a list/online audience, sync them
            into an OF custom list and pass `excluded_user_lists`
            (see audiences.ensure_exclude_list).
          - `excluded_user_lists`: custom list ids excluded server-side — the
            wire field is `excludedLists` (VERIFIED LIVE 2026-06-12; the old
            `excludeUserLists` name was silently ignored).
          - `online_only=True` (or `filters={'online': 1}`): native
            online-fan targeting — OF resolves the audience to fans currently
            online at send time. VERIFIED LIVE: OF web's "online" broadcast
            (referer /my/chats/send?list=users&online=1) posts exactly
            `{"filters":{"online":1},"userLists":["fans"]}`. Combine with
            `user_lists=['fans']` to blast every online fan.
        `scheduled_date`: ISO 8601 with offset — omit for immediate send."""
        text = _guard_outbound(text)
        merged_filters = dict(filters) if filters else {}
        if online_only:
            merged_filters["online"] = 1
        excl_ids = {int(u) for u in (excluded_users or [])}
        body: dict = {
            "text": text,
            "lockedText": locked_text,
            "mediaFiles": media_files or [],
            "price": price,
            "previews": previews or [],
            "userLists": user_lists or [],
            "userIds": [int(u) for u in (included_users or []) if int(u) not in excl_ids],
            "excludedLists": excluded_user_lists or [],
        }
        if merged_filters:
            body["filters"] = merged_filters
        if scheduled_date:
            body["scheduledDate"] = scheduled_date
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        if giphy_id:
            # Same wire-shape as the chat send: top-level `giphyId`, sibling
            # of `mediaFiles`. OF web includes GIFs on broadcasts; mirror the
            # field so the relay forwards rather than dropping silently.
            body["giphyId"] = str(giphy_id)
        return self._post_dropping_auto_cotag(
            f"{API_BASE}/messages/queue", body, retry_plan)

    # ── Posts: write ───────────────────────────────────────────

    def create_post(self, text: str, *,
                    media_files: list[int] | None = None,
                    price: int | float = 0,
                    previews: list[int] | None = None,
                    posted_at: str | None = None,
                    carrier_posted_at: str | None = None,
                    save_for_later: bool = False,
                    expire_days: int | None = None,
                    fund_raising_target: float | None = None,
                    fund_raising_presets: list[float] | None = None,
                    voting_type: int | None = None,
                    voting_options: list[str] | None = None,
                    voting_due: int | None = None,
                    voting_correct_index: int | None = None,
                    label_ids: list[int] | None = None,
                    tagged_users: list[int] | None = None,
                    giphy_id: str | None = None,
                    auto_tag: bool = True) -> Any:
        """POST /api2/v2/posts — create a feed post.
        `previews` = media ids (⊆ media_files) shown FREE as the teaser on a PAID
        post; the wire field is `preview` (singular) — CONFIRMED live 2026-06-22:
        a 21-media $60 post stored exactly the 5 passed ids in its `preview` array,
        the other 16 paywalled.
        `giphy_id` rides along as top-level `giphyId`, mirroring chat sends.

        The rest is the one place our names become OF's, as OF's own composer
        (`MakeFeedPost getDataObject`, build 202610091632) sends them; none of
        these is verified live yet:
        `posted_at` (ISO with offset) -> `isScheduled: 1` + `scheduledDate`;
        `save_for_later` -> `isScheduled: 1` + `isPublishedWithPeriod: 1`, no date;
        `expire_days` -> `expireDays`; `fund_raising_target` -> `fundRaisingTargetAmount`
        with `fundRaisingTipsPresets` (OF sends neither alone; its composer's default
        preset is [5]); `voting_options` -> `votingOptions` with `votingType`
        (1 poll, 2 quiz), `votingDue` (days) and, for a quiz, `votingCorrectIndex`;
        `label_ids` -> `labelIds` (post labels, GET/POST /labels).

        `carrier_posted_at` -> the OLD `postedAt` key, kept for the vault carrier
        alone (materialize_to_vault): that body is the one the vault import was
        verified live on (2026-09-08). Move the carrier to `posted_at` only after
        `isScheduled` + `scheduledDate` is verified live to keep a post unpublished."""
        text = _guard_outbound(text)
        body = self._post_body(
            text, media_files=media_files, price=price, previews=previews,
            posted_at=posted_at, save_for_later=save_for_later,
            expire_days=expire_days, fund_raising_target=fund_raising_target,
            fund_raising_presets=fund_raising_presets, voting_type=voting_type,
            voting_options=voting_options, voting_due=voting_due,
            voting_correct_index=voting_correct_index, label_ids=label_ids)
        if carrier_posted_at:   body["postedAt"] = carrier_posted_at
        if giphy_id:            body["giphyId"] = str(giphy_id)
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        result = self._post_dropping_auto_cotag(
            f"{API_BASE}/posts", body, retry_plan)
        # Proof a poll went out (02-gaps G2); never the text or the options.
        log_of.info("create_post has_voting=%s options_count=%d of_post_id=%s",
                    "votingOptions" in body, len(body.get("votingOptions") or ()),
                    result.get("id") if isinstance(result, dict) else None)
        return result

    @staticmethod
    def _post_body(text: str, *, media_files=None, price: int | float = 0,
                   previews=None, posted_at: str | None = None,
                   save_for_later: bool = False, expire_days: int | None = None,
                   fund_raising_target: float | None = None,
                   fund_raising_presets=None, voting_type: int | None = None,
                   voting_options=None, voting_due: int | None = None,
                   voting_correct_index: int | None = None,
                   label_ids=None) -> dict:
        """OF's post body (`MakeFeedPost getDataObject`): create_post's and
        edit_post's, the one place our names become OF's keys."""
        body: dict = {
            "text": text,
            "mediaFiles": media_files or [],
            "price": price,
        }
        if previews:            body["preview"] = [int(p) for p in previews]
        if posted_at:
            body["isScheduled"] = 1
            body["scheduledDate"] = posted_at
        if save_for_later:
            body["isScheduled"] = 1
            body["isPublishedWithPeriod"] = 1
        if expire_days:         body["expireDays"] = int(expire_days)
        if fund_raising_target:
            body["fundRaisingTargetAmount"] = fund_raising_target
            body["fundRaisingTipsPresets"] = list(fund_raising_presets or [5])
        if voting_options:
            body["votingType"] = voting_type or 1
            body["votingOptions"] = list(voting_options)
            if voting_due:      body["votingDue"] = int(voting_due)
            if body["votingType"] == 2 and voting_correct_index is not None:
                body["votingCorrectIndex"] = int(voting_correct_index)
        if label_ids:           body["labelIds"] = [int(i) for i in label_ids]
        return body

    def edit_post(self, post_id: int, *,
                  text: str | None = None,
                  price: float | None = None,
                  media_files: list[int] | None = None) -> Any:
        """PUT /api2/v2/posts/{post_id}."""
        body: dict = {}
        if text is not None:        body["text"] = text
        if price is not None:       body["price"] = price
        if media_files is not None: body["mediaFiles"] = media_files
        return self.put_json(f"{API_BASE}/posts/{post_id}", json_body=body)

    def save_queued_post(self, post_id: int, text: str, *,
                         tagged_users: list[int] | None = None, **fields) -> Any:
        """PUT /api2/v2/posts/{post_id} — save a post in place (OF's Edit post:
        MakeFeedPost sends `px(post.id, getDataObject())`, the create body).
        A scheduled post keeps `isScheduled` + `scheduledDate` (a new date is
        OF's reschedule), a saved-for-later one `isPublishedWithPeriod`.
        `fields`: _post_body's. No auto co-tag (the post's own tags are the
        operator's picks). Not verified live (no live write was made)."""
        body = self._post_body(text, **fields)
        self._apply_cotags(body, fields.get("media_files"), tagged_users, False)
        return self.put_json(f"{API_BASE}/posts/{post_id}", json_body=body)

    def delete_post(self, post_id: int) -> Any:
        """DELETE /api2/v2/posts/{post_id}."""
        return self.delete_json(f"{API_BASE}/posts/{post_id}")

    def like_post(self, post_id: int, author_id: int | str | None = None) -> Any:
        """POST /api2/v2/posts/{post_id}/favorites/{author_id}: OF's web client
        sends the post's AUTHOR id (module 458723 `p`, `{id, authorId}`).
        Defaults to `self.user_id`, the author of the Creator's own posts."""
        return self.post_json(f"{API_BASE}/posts/{post_id}/favorites/{author_id or self.user_id}")

    def unlike_post(self, post_id: int, author_id: int | str | None = None) -> Any:
        """POST /api2/v2/posts/{post_id}/favorites/{author_id} again: OF's web
        client toggles a like with the same POST (module 458723), never DELETE.
        Another creator's post needs its author, as for `like_post`."""
        return self.like_post(post_id, author_id)

    def comment_on_post(self, post_id: int, text: str) -> Any:
        """POST /api2/v2/posts/{post_id}/comments."""
        return self.post_json(f"{API_BASE}/posts/{post_id}/comments",
                              json_body={"text": text})

    def pin_post(self, post_id: int) -> Any:
        """POST /api2/v2/posts/{post_id}/pin?format=status — OF's web client's
        pin toggle (module 458723): the same request pins and unpins."""
        return self.post_json(f"{API_BASE}/posts/{post_id}/pin",
                              params={"format": "status"})

    def unpin_post(self, post_id: int) -> Any:
        """The pin toggle again (see pin_post); OF's web client never DELETEs it."""
        return self.pin_post(post_id)

    def archive_post(self, post_id: int) -> Any:
        """POST /api2/v2/posts/{post_id}/archive — OF's web client's "archive"
        (module 458723 `hf`, no query: the public archive). The response
        carries `counters` and `labelStates`."""
        return self.post_json(f"{API_BASE}/posts/{post_id}/archive")

    # ── Fan lists: write ───────────────────────────────────────

    def create_list(self, name: str) -> Any:
        """POST /api2/v2/lists — create custom fan list."""
        return self.post_json(f"{API_BASE}/lists", json_body={"name": name})

    def rename_list(self, list_id: str | int, name: str) -> Any:
        """PATCH /api2/v2/lists/{list_id} — OF uses PATCH (not PUT) for list rename.
        VERIFIED LIVE. Returns the full updated list object."""
        return self.request_json("PATCH", f"{API_BASE}/lists/{list_id}", json_body={"name": name})

    def delete_list(self, list_id: int) -> Any:
        """DELETE /api2/v2/lists/{list_id}."""
        return self.delete_json(f"{API_BASE}/lists/{list_id}")

    def add_user_to_list(self, list_id: int, user_id: int) -> Any:
        """POST /api2/v2/lists/{list_id}/users/{user_id}."""
        return self.post_json(f"{API_BASE}/lists/{list_id}/users/{user_id}")

    def remove_user_from_list(self, list_id: int, user_id: int) -> Any:
        """DELETE /api2/v2/lists/{list_id}/users/{user_id}."""
        return self.delete_json(f"{API_BASE}/lists/{list_id}/users/{user_id}")

    def clear_list(self, list_id: str | int) -> Any:
        """DELETE /api2/v2/lists/{list_id}/users — OF's "Clear list": every user leaves it."""
        return self.delete_json(f"{API_BASE}/lists/{list_id}/users")

    def add_users_to_lists(self, users_by_list: dict[str, list[int]]) -> Any:
        """POST /api2/v2/lists/users — bulk add, `{"<listId>": [userId, ...]}`. OF answers
        the same keys with the user ids now in each list (its own client checks every
        sent id came back)."""
        return self.post_json(f"{API_BASE}/lists/users", json_body=users_by_list)

    def set_list_pinned_to_chat(self, list_id: int | str, pinned: bool) -> dict:
        """PATCH /api2/v2/lists/{id} — pin/unpin a fan list as a chat folder.
        Captured DevTools: `{"isPinnedToChat": true|false}`."""
        return self.request_json("PATCH", f"{API_BASE}/lists/{list_id}",
                                  json_body={"isPinnedToChat": pinned})

    # ── Labels: write ──────────────────────────────────────────

    def create_label(self, name: str) -> Any:
        """POST /api2/v2/labels {name} — a new post label (OF module 91019)."""
        return self.post_json(f"{API_BASE}/labels", json_body={"name": name})

    def sort_labels(self, *, sort: str, order: str) -> Any:
        """POST /api2/v2/labels/sort {sort, order} — the labels' Sort menu
        (labels/savePostLabelsOrder: recent | name | posts | custom, asc | desc)."""
        return self.post_json(f"{API_BASE}/labels/sort", json_body={"sort": sort, "order": order})

    # ── Release forms: write ───────────────────────────────────

    def toggle_release_form(self, *, entity_id: int, entity_type: str) -> Any:
        """PATCH /api2/v2/release-forms/toggle-show {entityId, entityType} —
        a tag row's Hide / Unhide (releaseForms/hideReleaseForms)."""
        return self.request_json("PATCH", f"{API_BASE}/release-forms/toggle-show",
                                 json_body={"entityId": entity_id, "entityType": entity_type})

    def create_guest(self, *, name: str) -> Any:
        """POST /api2/v2/guests/ {name} — "Invite new user" (releaseForms/saveGuest):
        OF answers with the guest's token for its `?rfguesttoken=` invite link."""
        return self.post_json(f"{API_BASE}/guests/", json_body={"name": name})

    # ── Vault: write ───────────────────────────────────────────

    def hide_vault_media(self, media_ids: list[int]) -> dict:
        """PUT /api2/v2/vault/media/hidden — OF's own "Remove from vault".

        This IS what the OF web app does when you select vault items and click
        Remove: `deleteMedias()` → confirm dialog → `hideMedia()` →
        `hideMediaVaultByIds()` → this endpoint with {"mediaIds": [...]}, after
        which the store sets `hidden = true` on each item (read out of OF's own
        bundle, `041_46939.js`).

        There is NO hard-delete for vault media in OF's API — the only vault
        DELETEs are on `vault/lists` (folders). So this hides the media from the
        vault for real, on OnlyFans, WITHOUT destroying it: anything already
        attached to a sent PPV or a live post keeps working. No unhide call
        exists in OF's bundle either, so treat it as one-way.
        """
        ids = [int(m) for m in media_ids]
        if not ids:
            return {"success": True, "hidden": 0}
        return self.put_json(f"{API_BASE}/vault/media/hidden",
                             json_body={"mediaIds": ids})

    def create_vault_list(self, name: str) -> dict:
        """POST /api2/v2/vault/lists — create a custom vault folder.
        CONFIRMED wire shape (captured live 2026-07-20): body {"name": <str>} →
        {id, type:"custom", name, canUpdate, canDelete, ...counts, medias:[]}."""
        return self.post_json(f"{API_BASE}/vault/lists", json_body={"name": name})

    def add_media_to_vault_list(self, list_id: int, media_ids: list[int]) -> dict:
        """POST /api2/v2/vault/lists/{id}/media — add media to a folder.
        CONFIRMED (captured live): body {"mediaIds": [<int>,...]} → updated
        folder dict with new counts + medias."""
        return self.post_json(
            f"{API_BASE}/vault/lists/{int(list_id)}/media",
            json_body={"mediaIds": [int(m) for m in media_ids]},
        )

    def remove_media_from_vault_list(self, list_id: int, media_ids: list[int]) -> dict:
        """DELETE /api2/v2/vault/lists/{id}/media — take media out of a folder.
        The media stay in the vault. Shape read from OF's web bundle (module
        551564 `Lg`): body {"mediaIds": [<int>,...]} → updated folder dict."""
        return self.delete_json(
            f"{API_BASE}/vault/lists/{int(list_id)}/media",
            json_body={"mediaIds": [int(m) for m in media_ids]},
        )

    def rename_vault_list(self, list_id: int, name: str) -> dict:
        """PATCH /api2/v2/vault/lists/{id} — rename a folder.
        CONFIRMED (captured live 2026-07-20): body {"name": <str>} → updated dict."""
        return self.request_json(
            "PATCH", f"{API_BASE}/vault/lists/{int(list_id)}",
            json_body={"name": name},
        )

    def delete_vault_list(self, list_id: int, clear_media: bool = False) -> dict:
        """DELETE /api2/v2/vault/lists/{id} — delete a folder. CONFIRMED:
        body {"clearMedia": <bool>} → {"success": true}. `clear_media=False`
        keeps the media in the vault (only removes the folder)."""
        return self.delete_json(
            f"{API_BASE}/vault/lists/{int(list_id)}",
            json_body={"clearMedia": bool(clear_media)},
        )

    def sort_vault_lists(self, sort: str = "recent", order: str = "desc") -> dict:
        """POST /api2/v2/vault/lists/sort — set the folder-list ordering.
        CONFIRMED: {"sort": "name|recent|media|custom|default", "order": "asc|desc"}."""
        return self.post_json(
            f"{API_BASE}/vault/lists/sort",
            json_body={"sort": sort, "order": order},
        )

    def set_vault_lists_custom_order(self, list_ids: list[int]) -> dict:
        """POST /api2/v2/vault/lists/sort — set a manual folder order (drag).
        CONFIRMED: {"customOrder": [<list_id>,...], "sort": "custom"}."""
        return self.post_json(
            f"{API_BASE}/vault/lists/sort",
            json_body={"customOrder": [int(i) for i in list_ids], "sort": "custom"},
        )

    # ── Payouts: write ─────────────────────────────────────────

    def request_payout(self, withdrawal_amount: float) -> Any:
        """POST /api2/v2/payouts/requests — a manual withdrawal, as OF's
        Statements "Request withdrawal" dialog sends it: {withdrawal_amount}.
        OF answers below the balance/minimum with 400
        {"error":{"code":0,"message":"Not enough funds to request a payout"}}."""
        return self.request_json("POST", f"{API_BASE}/payouts/requests",
                                 json_body={"withdrawal_amount": withdrawal_amount})

    def update_withdrawal_period(self, withdrawal_period: str) -> Any:
        """PATCH /api2/v2/payouts/requests — the payout frequency, as OF's
        Statements select sends it: {withdrawalPeriod: <a withdrawalPeriodOptions
        code: manual | weekly | monthly>}. Answers {"success": true}."""
        return self.request_json("PATCH", f"{API_BASE}/payouts/requests",
                                 json_body={"withdrawalPeriod": withdrawal_period})

    # ── Fan note + custom name ─────────────────────────────────
    # FOUND via Playwright UI capture (chat 800000778):
    # `PUT /subscriptions/{user_id}` with `{notice}` OR `{displayName}` body.
    # ONE endpoint, TWO fields — clear in OF UI as "fan notes" + "custom name"
    # but they share the same OF API call. The fields can be sent together or
    # separately. Send empty string to clear.

    def set_fan_note(self, user_id: str | int, note: str) -> Any:
        """PUT /api2/v2/subscriptions/{user_id} {"notice": ...} — the private
        creator-side note on a fan. Pass empty string to clear. VERIFIED LIVE."""
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}",
                             json_body={"notice": note})

    def set_fan_custom_name(self, user_id: str | int, name: str) -> Any:
        """PUT /api2/v2/subscriptions/{user_id} {"displayName": ...} — custom
        nickname shown next to the fan's username. Empty string to clear.
        VERIFIED LIVE."""
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}",
                             json_body={"displayName": name})

    def update_subscription(self, user_id: str | int, **fields) -> Any:
        """PUT /api2/v2/subscriptions/{user_id} — generic version of the above.
        Pass `notice=`, `displayName=`, or any other accepted field together."""
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}", json_body=fields)

    # ── Streams: write ─────────────────────────────────────────

    def schedule_stream(self, **fields) -> Any:
        """POST /api2/v2/streams — schedule a stream. OF's own create form sends
        {description, scheduledDate, isShowTips: true} (scheduledDate a local
        ISO string with offset, e.g. 2026-10-20T18:30:00+02:00; optional
        mediaFiles for a cover). Returns the stream, `.id` included."""
        if not fields:
            raise ValueError("at least one field required")
        return self.post_json(f"{API_BASE}/streams", json_body=fields)

    # ── Stories ────────────────────────────────────────────────
    # Captured live (HAR: "pick image from vault and upload it as story").
    # KEY FINDING: /stories does NOT take a vault media id. Even when the UI
    # picks an existing vault image, OF re-runs the FULL fresh-upload pipeline
    # (signed/create → S3 PUT → convert.onlyfans.com/file/upload) and posts
    # the convert claim — NOT the vault id. So "post from vault/CDN" really
    # means: fetch the image bytes, push them through upload_media(), then
    # hand the resulting `send_with` (`[{processId, host, name, extra}]`) to
    # create_story(). Observed wire body:
    #   POST /api2/v2/stories
    #   {"mediaFiles":[{processId,name,host,extra}],
    #    "rfTag":[],"rfGuest":[],"rfPartner":[]}

    # Overlay geometry — the EXACT values the OF web editor emitted (HAR
    # "storiewith added text question and tag2.har"). We replay them verbatim
    # so each overlay lands center-ish, "as is by default", just like the
    # editor produced. Coordinates are in the 192 x 347 canvas space.
    _STORY_CANVAS = {"canvasWidth": 192, "canvasHeight": 347}
    _STORY_TEXT_PRESET = {
        "left": 19.58615311, "top": 40.55326425,
        "scale": 1.7993021042613935, "angle": 0,
        "color": "#ffffff", "fontSize": "19.88px", "fontWeight": "400",
        "fontFamily": "Roboto", "textAlign": "left", "bgColor": "#00000000",
        "type": "text",
        "textWidth": 117.31449719784288, "textHeight": 65.56034611398962,
        "zIndex": 2,
    }
    _STORY_MENTION_PRESET = {
        "left": 9.5119356, "top": 29.47480311,
        "scale": 1.7993021042613935, "angle": 0,
        "color": "#0091ea", "fontSize": "19.88px", "fontWeight": "500",
        "fontFamily": "Roboto", "textAlign": "left", "bgColor": "#ffffff",
        "type": "mention",
        "textWidth": 138.00647139684892, "textHeight": 192.78683533678753,
        "zIndex": 3,
    }
    _STORY_QUESTION_PRESET = {
        "left": 20.60537168, "top": 38.39384914, "angle": 0,
        "width": 115.19999999613947, "height": 71.70088386428068,
        "color": "#FFFFFF", "zIndex": 4,
    }

    def create_story(self, media_files: list, *,
                     caption: str | None = None,
                     mention: str | None = None,
                     question: str | None = None) -> Any:
        """POST /api2/v2/stories — publish a story from already-prepared media,
        optionally with a text caption, an @mention tag, and a question sticker.

        `media_files` is the `mediaFiles` array verbatim — pass the
        `send_with` list returned by upload_media() (fresh-claim shape
        `[{processId, host, name, extra}]`). Bare vault ids are NOT accepted
        by this endpoint (unlike posts/messages), so always feed it a convert
        claim. rf* arrays mirror posts/creator-DMs and must be present.

        Overlays (`caption`/`mention`/`question`) reuse the captured editor
        geometry (see the *_PRESET dicts). When any overlay is present we also
        send `canvasWidth/Height` and a `mediaEditorFiles` entry per media
        (keyed by processId), exactly as OF's JS does."""
        body: dict = {
            "mediaFiles": media_files,
            "rfTag": [],
            "rfGuest": [],
            "rfPartner": [],
        }

        # texts is an index-keyed map ("0","1",...). Caption goes first (z2),
        # mention second (z3) — same ordering OF's editor emitted.
        texts: dict = {}
        if caption:
            texts[str(len(texts))] = {**self._STORY_TEXT_PRESET, "text": caption}
        if mention:
            handle = mention if mention.startswith("@") else f"@{mention}"
            texts[str(len(texts))] = {**self._STORY_MENTION_PRESET, "text": handle}

        has_overlay = bool(texts) or bool(question)
        if has_overlay:
            body.update(self._STORY_CANVAS)
        if question:
            body["question"] = {**self._STORY_QUESTION_PRESET, "text": question}
        if texts:
            body["texts"] = texts
        if has_overlay:
            editor: dict = {}
            for mf in media_files:
                pid = mf.get("processId") if isinstance(mf, dict) else None
                if pid:
                    editor[pid] = {"baseFile": {}, "stickers": []}
            if editor:
                body["mediaEditorFiles"] = editor

        return self.post_json(f"{API_BASE}/stories", json_body=body)

    def delete_story(self, story_id: int) -> Any:
        """DELETE /api2/v2/stories/{story_id} — remove one of my stories.
        Story dicts carry `canDelete: true` for ones I own. Used by the
        unsend_messages story cleanup leg + the auto_stories automation."""
        return self.delete_json(f"{API_BASE}/stories/{story_id}")

    def post_story(self, file_path: str | Path, *,
                   content_type: str | None = None,
                   watermark_text: str | None = None,
                   caption: str | None = None,
                   mention: str | None = None,
                   question: str | None = None,
                   return_upload: bool = False) -> Any:
        """Upload a local file and publish it as a story in one call.

        Forces the fresh-upload path (check_dedupe=False): /stories only
        accepts a convert claim, and a dedupe hit returns a bare vault id
        that stories rejects.

        `return_upload=True` returns `{"story": <resp>, "upload": {md5, size}}`
        instead of the bare story dict, so the caller can later find and hide
        the vault dupe this fresh upload creates (see upload_media's `md5`)."""
        up = self.upload_media(
            file_path, content_type=content_type,
            check_dedupe=False, watermark_text=watermark_text,
        )
        if not up.get("ready") or not up.get("send_with"):
            raise OFAPIError(f"story media not ready: {up.get('note')}")
        story = self.create_story(
            up["send_with"], caption=caption, mention=mention, question=question,
        )
        if return_upload:
            return {"story": story, "upload": {"md5": up.get("md5"), "size": up.get("size")}}
        return story

    def post_story_from_url(self, media_url: str, *,
                            content_type: str | None = None,
                            watermark_text: str | None = None,
                            caption: str | None = None,
                            mention: str | None = None,
                            question: str | None = None,
                            return_upload: bool = False) -> Any:
        """Download an image (vault CDN url or any image url) and publish it
        as a story. This is the "post from vault / from CDN" path: a vault
        item's `files.full.url` (or a thumbs/cdn url) is fetched, re-uploaded
        through OF's convert pipeline, then posted.

        `return_upload=True` bubbles the `{story, upload:{md5,size}}` shape up
        from post_story (used by auto_stories to hide the re-uploaded dupe)."""
        import tempfile, os, mimetypes
        r = self._proxy_retry(
            lambda: self.http.get(media_url, timeout=max(self.timeout_s, 60)),
            what="cdn-download",
        )
        if not r.ok:
            raise OFAPIError(f"download failed: {r.status_code} for {media_url[:120]}")
        data = r.content or b""
        if not data:
            raise OFAPIError(f"download empty for {media_url[:120]}")
        ct = content_type or r.headers.get("content-type", "").split(";")[0].strip() \
            or "image/jpeg"
        suffix = mimetypes.guess_extension(ct) or ".jpg"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            return self.post_story(
                tmp_path, content_type=ct, watermark_text=watermark_text,
                caption=caption, mention=mention, question=question,
                return_upload=return_upload,
            )
        finally:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass


# Last, not first: of_client imports this module while it loads, and these
# names are read only when a method runs, so either import order works.
from of_client import (  # noqa: E402
    API_BASE, OFAPIError, _CoTagRetry, _guard_outbound, _wrap_text_as_p,
    _write_tag_block, log_of,
)
