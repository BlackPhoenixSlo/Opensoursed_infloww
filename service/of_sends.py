from __future__ import annotations

from pathlib import Path
from typing import Any

import send_tripwire


class SendsMixin:


    # Co-tag rides `rfTag`, never `userTags`: OF's client never emits userTags and /messages/queue stored releaseForms [] for it; userTags stays as harmless.
    def _apply_cotags(self, body: dict, media_files, tagged_users,
                      auto_tag: bool) -> _CoTagRetry | None:
        # Retry plan is a local, not self state: one OFClient is shared across accounts' concurrent to_thread sends.
        explicit = [int(u) for u in (tagged_users or [])]
        extra: list[int] = []
        if auto_tag:
            try:
                import media_cotag
                extra = [u for u in media_cotag.cotags_for(self, media_files)
                         if u not in explicit]
            except Exception:
                log_of.exception("co-performer tag resolution failed — sending as-is")
        native_rf = "rfTag" in body
        _write_tag_block(body, explicit + extra, native_rf=native_rf)
        return _CoTagRetry(explicit, native_rf) if extra else None

    # OF 400s the whole send on a tag id it rejects: retry once with our auto-tag dropped, keeping the operator's picks.
    def _post_dropping_auto_cotag(self, path: str, body: dict,
                                  retry_plan: _CoTagRetry | None):
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
            try:
                # Forget the refused id or every send pays POST -> 400 -> POST until the resolver TTL.
                import media_cotag
                media_cotag.forget_tag_id(getattr(self, "account_id", ""))
            except Exception:
                log_of.exception("could not invalidate the rejected co-tag id")
            retry = dict(body)
            _write_tag_block(retry, retry_plan.keep,
                             native_rf=retry_plan.native_rf)
            return self.post_json(path, json_body=retry)

    def _consent(self, body: dict) -> None:
        of_consent.apply(body, getattr(self, "account_id", None))


    def send_message(self, chat_id: str | int, text: str, **kwargs: Any) -> dict:
        return self.post_message(*self.prepare_message(chat_id, text, **kwargs))

    def post_message(self, chat_id: str | int, path: str, body: dict, retry_plan: _CoTagRetry | None) -> dict:
        send_tripwire.check("post_message")
        import sends_inflight
        account_id = getattr(self, "account_id", None)
        pending = sends_inflight.begin(account_id, chat_id)
        try:
            result = self._post_dropping_auto_cotag(path, body, retry_plan)
        except Exception:
            sends_inflight.post_finished(account_id, chat_id, pending)
            raise
        sends_inflight.post_finished(account_id, chat_id, pending,
                                    result.get("id") if isinstance(result, dict) else None)
        return result

    def prepare_message(self, chat_id: str | int, text: str, *,
                     locked_text: bool = False, price: int | float = 0,
                     media_files: list | None = None,
                     previews: list[int] | None = None,
                     is_forward: bool = False,
                     reply_to_message_id: int | None = None,
                     tagged_users: list[int] | None = None,
                     giphy_id: str | None = None,
                     rf_guest: list[int] | None = None,
                     rf_partner: list[int] | None = None,
                     auto_tag: bool = True) -> tuple[str | int, str, dict, _CoTagRetry | None]:
        text = _guard_outbound(text, chat=True)
        body = self._message_body(
            text, locked_text=locked_text, price=price, media_files=media_files,
            previews=previews, is_forward=is_forward,
            reply_to_message_id=reply_to_message_id, giphy_id=giphy_id,
            rf_guest=rf_guest, rf_partner=rf_partner)
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        self._consent(body)
        log_of.info(
            "send_message chat=%s price=%s mediaFiles=%r previews=%r "
            "userTags=%r rfTag=%r giphyId=%r",
            chat_id, price, body["mediaFiles"], body["previews"],
            body.get("userTags") or [], body.get("rfTag") or [],
            body.get("giphyId"),
        )
        import dm_rate
        dm_rate.record(getattr(self, "account_id", None))
        path = f"{API_BASE}/chats/{chat_id}/messages"
        return chat_id, path, body, retry_plan

    @staticmethod
    def _message_body(text: str, *, locked_text: bool,
                      price: int | float, media_files: list | None,
                      previews: list[int] | None, is_forward: bool,
                      reply_to_message_id: int | None,
                      giphy_id: str | None,
                      rf_guest: list[int] | None,
                      rf_partner: list[int] | None) -> dict:
        # OF web wraps text in <p> (creator-to-creator sends require it); a GIF send keeps "" and uses top-level giphyId.
        wrapped_text = "" if (giphy_id and not text) else _wrap_text_as_p(text)
        body = {
            "text": wrapped_text,
            "lockedText": locked_text,
            "mediaFiles": media_files or [],
            "price": price,
            # Unlocked teasers when price > 0; OF ignores previews on free messages.
            "previews": previews or [],
            # OF web always sends the release-form arrays; omitting them 400s creator-to-creator sends.
            "rfTag": [],
            "rfGuest": [int(i) for i in (rf_guest or [])],
            "rfPartner": [int(i) for i in (rf_partner or [])],
            "isForward": is_forward,
        }
        if giphy_id:
            body["giphyId"] = str(giphy_id)
        if reply_to_message_id is not None:
            body["replyToMessageId"] = reply_to_message_id
        return body


    # DESTRUCTIVE, only inside OF's edit window (~24h); pass with_user_id or a mass bubble's response omits the queue block.
    def unsend_message(self, message_id: int, with_user_id: int | None = None) -> Any:
        body: dict | None = {"withUserId": int(with_user_id)} if with_user_id is not None else None
        return self.delete_json(f"{API_BASE}/messages/{message_id}", json_body=body)

    # Only the other party's messages can be liked (own -> 404).
    def like_message(self, message_id: int) -> Any:
        return self.post_json(f"{API_BASE}/messages/{message_id}/like")

    def unlike_message(self, message_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/messages/{message_id}/like")

    # TOGGLE: pinning an already-pinned message unpins it and still answers success; check get_pinned_messages first. The long /pin/user form is what OF web sends.
    def pin_message(self, message_id: int, user_id: int | str) -> Any:
        return self.post_json(f"{API_BASE}/messages/{message_id}/pin/user/{user_id}")

    def unpin_message(self, message_id: int, user_id: int | str) -> Any:
        return self.delete_json(f"{API_BASE}/messages/{message_id}/pin/user/{user_id}")

    def unpin_all_messages(self, chat_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/messages/pin")

    def hide_message(self, message_id: int, with_user_id: int) -> Any:
        return self.put_json(f"{API_BASE}/messages/{message_id}/hide",
                             json_body={"withUserId": int(with_user_id)})

    def bookmark_message(self, message_id: int, chat_group_id: int | None, on: bool) -> Any:
        body = {"chat_group_id": chat_group_id} if chat_group_id is not None else None
        if on:
            return self.post_json(f"{API_BASE}/posts/{message_id}/bookmarks", json_body=body)
        return self.delete_json(f"{API_BASE}/posts/{message_id}/bookmarks", json_body=body)


    def mark_chat_read(self, chat_id: str | int) -> Any:
        return self.post_json(f"{API_BASE}/chats/{chat_id}/mark-as-read")

    def mark_chat_unread(self, chat_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/mark-as-read")

    def mark_all_chats_read(self) -> Any:
        return self.post_json(f"{API_BASE}/chats/mark-as-read")

    def notifications_read(self) -> Any:
        return self.post_json(f"{API_BASE}/users/notifications/read")

    def mute_chat(self, chat_id: str | int) -> Any:
        return self.post_json(f"{API_BASE}/chats/{chat_id}/mute")

    def unmute_chat(self, chat_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/mute")

    def hide_chat(self, chat_id: str | int) -> Any:
        return self.post_json(f"{API_BASE}/chats/{chat_id}/hide")

    def unhide_chat(self, chat_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/chats/{chat_id}/hide")

    def delete_chat(self, chat_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/chats/{chat_id}")


    def block_user(self, user_id: str | int) -> Any:
        return self.post_json(f"{API_BASE}/users/{user_id}/block")

    def unblock_user(self, user_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/users/{user_id}/block")

    def block_stream_viewer(self, username: str) -> Any:
        return self.post_json(f"{API_BASE}/streams/users/{username}/block")

    def unblock_stream_viewer(self, user_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/streams/users/{user_id}/block")

    def restrict_user(self, user_id: str | int) -> Any:
        return self.post_json(f"{API_BASE}/users/{user_id}/restrict")

    def unrestrict_user(self, user_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/users/{user_id}/restrict")


    # MONEY: subscribe is free only when subscribePrice == 0, else it charges the creator; callers must gate.
    def follow_user(self, user_id: str | int) -> Any:
        return self.post_json(f"{API_BASE}/users/{user_id}/subscribe", json_body={})

    # `reason` is required (empty body 400s "Invalid reason").
    def unfollow_user(self, user_id: str | int, *, reason_id: int = 1) -> Any:
        return self.delete_json(f"{API_BASE}/users/{user_id}/subscribe",
                                json_body={"reason": reason_id})

    # Only for a lapsed/expired relationship; right after an unfollow it 400s, re-follow via follow_user.
    def resubscribe_user(self, user_id: str | int) -> Any:
        return self.post_json(f"{API_BASE}/users/{user_id}/resubscribe", json_body={})

    def add_link_claimers_to_list(self, list_id: str | int, kind: str, link_id: int) -> Any:
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


    def set_subscription_discount(self, user_id: str | int, discount: int, period: int) -> Any:
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}/discount",
                             json_body={"discount": int(discount), "period": int(period)})


    def set_reply_on_subscribe(self, enabled: bool) -> Any:
        return self.request_json(
            "PATCH", f"{API_BASE}/users/me",
            json_body={"replyOnSubscribe": bool(enabled)},
        )

    def create_bundle(self, *, months: int | None = None, price: float | None = None,
                      discount: int | None = None, duration: int | None = None) -> Any:
        if duration is not None:
            body: dict[str, Any] = {"discount": int(discount or 0), "duration": int(duration)}
        else:
            body = {"months": months, "price": price}
            if discount is not None: body["discount"] = discount
        return self.post_json(f"{API_BASE}/subscriptions/bundles",
                              json_body=body)

    def delete_bundle(self, bundle_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/subscriptions/bundles/{bundle_id}")

    def edit_bundle(self, bundle_id: int, *, discount: int, duration: int) -> Any:
        return self.put_json(f"{API_BASE}/subscriptions/bundles/{bundle_id}",
                             json_body={"discount": int(discount), "duration": int(duration),
                                        "id": int(bundle_id)})


    # OF requires `discount` (integer percent 1-100); `price` is invalid; the legacy price kwarg is ignored.
    def create_promo(self, *, subscribe_counts: int, subscribe_days: int = 30,
                     discount: int | None = None, message: str = "",
                     type: str | list[str] = "all", price: float | None = None,
                     finish_days: int | None = None) -> Any:
        if discount is None:
            raise ValueError("create_promo requires discount (integer percent 1-100)")
        body: dict[str, Any] = {
            "discount": max(1, min(int(discount), 100)),
            "subscribeCounts": subscribe_counts,
            "subscribeDays": subscribe_days,
            "message": message, "type": type,
        }
        if finish_days is not None:
            body["finishDays"] = int(finish_days)
        return self.post_json(f"{API_BASE}/promotions", json_body=body)

    def finish_promo(self, promo_id: int) -> Any:
        return self.post_json(f"{API_BASE}/promotions/{promo_id}/finish")

    def delete_promo(self, promo_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/promotions/{promo_id}")

    # Create body field is `name`; the LIST response spells it campaignName.
    def create_tracking_link(self, *, name: str, code: int | None = None) -> Any:
        body: dict[str, Any] = {"name": name}
        if code is not None:
            body["campaignCode"] = code
        return self.post_json(f"{API_BASE}/campaigns", json_body=body)

    def delete_tracking_link(self, campaign_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/campaigns/{campaign_id}")

    def create_trial_link(self, *, name: str, subscribe_days: int = 7,
                          subscribe_counts: int = 1,
                          expired_at: str | None = None,
                          expire_days: int | None = None) -> Any:
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
        return self.post_json(f"{API_BASE}/trials/share-access",
                              json_body={"trialId": int(trial_id), "userId": int(user_id)})

    def share_campaign_stats(self, *, campaign_id: int, user_id: int) -> Any:
        return self.post_json(f"{API_BASE}/campaigns/share-access",
                              json_body={"campaignId": int(campaign_id), "userId": int(user_id)})

    def unshare_campaign_stats(self, *, campaign_id: int, user_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/campaigns/share-access",
                                json_body={"campaignId": int(campaign_id), "userId": int(user_id)})

    def delete_trial_link(self, trial_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/trials/{trial_id}")


    def update_profile(self, **fields) -> Any:
        if not fields:
            raise ValueError("at least one field required")
        return self.request_json("PATCH", f"{API_BASE}/users/me", json_body=fields)


    def patch_security_settings(self, fields: dict) -> Any:
        if not fields:
            raise ValueError("at least one field required")
        return self.request_json("PATCH", f"{API_BASE}/users/me/settings/security", json_body=fields)

    def put_security_settings(self, fields: dict) -> Any:
        if not fields:
            raise ValueError("at least one field required")
        return self.request_json("PUT", f"{API_BASE}/users/me/settings/security", json_body=fields)

    def patch_notification_settings(self, body: dict) -> Any:
        if not body:
            raise ValueError("empty body")
        return self.request_json("PATCH", f"{API_BASE}/users/settings/notifications", json_body=body)

    def patch_story_settings(self, allow_reply_from: str) -> Any:
        return self.request_json("PATCH", f"{API_BASE}/users/settings/story",
                                 json_body={"allowReplyFrom": allow_reply_from})

    # Irreversible; `_denied` refuses it until the owner's go lifts that backstop.
    def close_all_sessions(self) -> Any:
        return self.request_json("DELETE", f"{API_BASE}/sessions")

    def add_social_button(self, body: dict) -> Any:
        if not body:
            raise ValueError("empty body")
        return self.request_json("PUT", f"{API_BASE}/users/social/buttons", json_body=body)

    def delete_social_button(self, button_id: int) -> Any:
        return self.request_json("DELETE", f"{API_BASE}/users/social/buttons/{int(button_id)}")

    def add_users_link(self, body: dict) -> Any:
        if not body:
            raise ValueError("empty body")
        return self.request_json("PUT", f"{API_BASE}/users/links", json_body=body)

    def delete_users_link(self, link_id: int) -> Any:
        return self.request_json("DELETE", f"{API_BASE}/users/links/{int(link_id)}")

    def reset_stream_key(self, server: str) -> Any:
        return self.delete_json(f"{API_BASE}/streams/obs/key", params={"type": server})



    def schedule_message(self, chat_id: str | int, text: str, *,
                         scheduled_date: str, price: int | float = 0,
                         locked_text: bool = False,
                         media_files: list[int] | None = None,
                         previews: list[int] | None = None,
                         tagged_users: list[int] | None = None,
                         auto_tag: bool = True) -> Any:
        send_tripwire.check("schedule_message")
        body = {
            "text": of_text(text),
            "lockedText": locked_text,
            "mediaFiles": media_files or [],
            "price": price,
            "previews": previews or [],
            "scheduledDate": scheduled_date,
            "userIds": [int(chat_id)],
        }
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        self._consent(body)
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
        send_tripwire.check("schedule_mass_message")
        # Date or save_for_later is required: a body with neither could send at once.
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
        self._consent(body)
        return self._post_dropping_auto_cotag(
            f"{API_BASE}/messages/queue", body, retry_plan)

    @staticmethod
    def _mass_body(*, text: str, user_ids, user_lists, excluded_users,
                   excluded_user_lists, price, locked_text, media_files,
                   previews, filters, online_only) -> dict:
        # OF has no per-user exclude field (excludedUsers is silently dropped): subtract client-side; list excludes use `excludedLists`.
        excl_ids = {int(u) for u in (excluded_users or [])}
        body: dict = {
            "text": of_text(text),
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
        # Date or save_for_later is required: a body with neither could send at once.
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
        self._consent(body)
        return self.put_json(f"{API_BASE}/messages/queue/{queue_id}", json_body=body)

    def cancel_scheduled(self, queue_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/messages/queue/{queue_id}")

    # Send the schedule item's own `id`, not its entity's.
    def publish_schedule(self, schedule_id: int) -> Any:
        send_tripwire.check("publish_schedule")
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
        send_tripwire.check("send_mass_message")
        text = _guard_outbound(text)
        merged_filters = dict(filters) if filters else {}
        if online_only:
            merged_filters["online"] = 1
        # OF has no per-user exclude field (excludedUsers is silently dropped): subtract client-side; list excludes use `excludedLists`.
        excl_ids = {int(u) for u in (excluded_users or [])}
        body: dict = {
            "text": of_text(text),
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
            body["giphyId"] = str(giphy_id)
        self._consent(body)
        return self._post_dropping_auto_cotag(
            f"{API_BASE}/messages/queue", body, retry_plan)


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
        send_tripwire.check("create_post")
        text = _guard_outbound(text)
        body = self._post_body(
            text, media_files=media_files, price=price, previews=previews,
            posted_at=posted_at, save_for_later=save_for_later,
            expire_days=expire_days, fund_raising_target=fund_raising_target,
            fund_raising_presets=fund_raising_presets, voting_type=voting_type,
            voting_options=voting_options, voting_due=voting_due,
            voting_correct_index=voting_correct_index, label_ids=label_ids)
        # Carrier keeps the old `postedAt` key (the body vault import was verified on); don't move it to posted_at until scheduling is verified.
        if carrier_posted_at:   body["postedAt"] = carrier_posted_at
        if giphy_id:            body["giphyId"] = str(giphy_id)
        retry_plan = self._apply_cotags(body, media_files, tagged_users, auto_tag)
        self._consent(body)
        result = self._post_dropping_auto_cotag(
            f"{API_BASE}/posts", body, retry_plan)
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
        body: dict = {
            "text": of_text(text),
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
        body: dict = {}
        if text is not None:        body["text"] = of_text(text)
        if price is not None:       body["price"] = price
        if media_files is not None: body["mediaFiles"] = media_files
        self._consent(body)
        return self.put_json(f"{API_BASE}/posts/{post_id}", json_body=body)

    def save_queued_post(self, post_id: int, text: str, *,
                         tagged_users: list[int] | None = None, **fields) -> Any:
        body = self._post_body(text, **fields)
        self._apply_cotags(body, fields.get("media_files"), tagged_users, False)
        self._consent(body)
        return self.put_json(f"{API_BASE}/posts/{post_id}", json_body=body)

    def delete_post(self, post_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/posts/{post_id}")

    def like_post(self, post_id: int, author_id: int | str | None = None) -> Any:
        return self.post_json(f"{API_BASE}/posts/{post_id}/favorites/{author_id or self.user_id}")

    # OF toggles a like with the same POST as like_post, never DELETE.
    def unlike_post(self, post_id: int, author_id: int | str | None = None) -> Any:
        return self.like_post(post_id, author_id)

    def comment_on_post(self, post_id: int, text: str) -> Any:
        return self.post_json(f"{API_BASE}/posts/{post_id}/comments",
                              json_body={"text": of_text(text)})

    # OF's pin is a toggle: the same request pins and unpins.
    def pin_post(self, post_id: int) -> Any:
        return self.post_json(f"{API_BASE}/posts/{post_id}/pin",
                              params={"format": "status"})

    def unpin_post(self, post_id: int) -> Any:
        return self.pin_post(post_id)

    def archive_post(self, post_id: int) -> Any:
        return self.post_json(f"{API_BASE}/posts/{post_id}/archive")


    def create_list(self, name: str) -> Any:
        return self.post_json(f"{API_BASE}/lists", json_body={"name": name})

    def rename_list(self, list_id: str | int, name: str) -> Any:
        return self.request_json("PATCH", f"{API_BASE}/lists/{list_id}", json_body={"name": name})

    def delete_list(self, list_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/lists/{list_id}")

    def add_user_to_list(self, list_id: int, user_id: int) -> Any:
        return self.post_json(f"{API_BASE}/lists/{list_id}/users/{user_id}")

    def remove_user_from_list(self, list_id: int, user_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/lists/{list_id}/users/{user_id}")

    def clear_list(self, list_id: str | int) -> Any:
        return self.delete_json(f"{API_BASE}/lists/{list_id}/users")

    def add_users_to_lists(self, users_by_list: dict[str, list[int]]) -> Any:
        return self.post_json(f"{API_BASE}/lists/users", json_body=users_by_list)

    def set_list_pinned_to_chat(self, list_id: int | str, pinned: bool) -> dict:
        return self.request_json("PATCH", f"{API_BASE}/lists/{list_id}",
                                  json_body={"isPinnedToChat": pinned})


    def create_label(self, name: str) -> Any:
        return self.post_json(f"{API_BASE}/labels", json_body={"name": name})

    def sort_labels(self, *, sort: str, order: str) -> Any:
        return self.post_json(f"{API_BASE}/labels/sort", json_body={"sort": sort, "order": order})


    def toggle_release_form(self, *, entity_id: int, entity_type: str) -> Any:
        return self.request_json("PATCH", f"{API_BASE}/release-forms/toggle-show",
                                 json_body={"entityId": entity_id, "entityType": entity_type})

    def create_guest(self, *, name: str) -> Any:
        return self.post_json(f"{API_BASE}/guests/", json_body={"name": name})


    # OF has no hard-delete for vault media: this hides it one-way; media already on a sent PPV or post keeps working.
    def hide_vault_media(self, media_ids: list[int]) -> dict:
        ids = [int(m) for m in media_ids]
        if not ids:
            return {"success": True, "hidden": 0}
        return self.put_json(f"{API_BASE}/vault/media/hidden",
                             json_body={"mediaIds": ids})

    def create_vault_list(self, name: str) -> dict:
        return self.post_json(f"{API_BASE}/vault/lists", json_body={"name": name})

    def add_media_to_vault_list(self, list_id: int, media_ids: list[int]) -> dict:
        return self.post_json(
            f"{API_BASE}/vault/lists/{int(list_id)}/media",
            json_body={"mediaIds": [int(m) for m in media_ids]},
        )

    def remove_media_from_vault_list(self, list_id: int, media_ids: list[int]) -> dict:
        return self.delete_json(
            f"{API_BASE}/vault/lists/{int(list_id)}/media",
            json_body={"mediaIds": [int(m) for m in media_ids]},
        )

    def rename_vault_list(self, list_id: int, name: str) -> dict:
        return self.request_json(
            "PATCH", f"{API_BASE}/vault/lists/{int(list_id)}",
            json_body={"name": name},
        )

    def delete_vault_list(self, list_id: int, clear_media: bool = False) -> dict:
        return self.delete_json(
            f"{API_BASE}/vault/lists/{int(list_id)}",
            json_body={"clearMedia": bool(clear_media)},
        )

    def sort_vault_lists(self, sort: str = "recent", order: str = "desc") -> dict:
        return self.post_json(
            f"{API_BASE}/vault/lists/sort",
            json_body={"sort": sort, "order": order},
        )

    def set_vault_lists_custom_order(self, list_ids: list[int]) -> dict:
        return self.post_json(
            f"{API_BASE}/vault/lists/sort",
            json_body={"customOrder": [int(i) for i in list_ids], "sort": "custom"},
        )


    def request_payout(self, withdrawal_amount: float) -> Any:
        return self.request_json("POST", f"{API_BASE}/payouts/requests",
                                 json_body={"withdrawal_amount": withdrawal_amount})

    def update_withdrawal_period(self, withdrawal_period: str) -> Any:
        return self.request_json("PATCH", f"{API_BASE}/payouts/requests",
                                 json_body={"withdrawalPeriod": withdrawal_period})


    def set_fan_note(self, user_id: str | int, note: str) -> Any:
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}",
                             json_body={"notice": note})

    def set_fan_custom_name(self, user_id: str | int, name: str) -> Any:
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}",
                             json_body={"displayName": name})

    def update_subscription(self, user_id: str | int, **fields) -> Any:
        return self.put_json(f"{API_BASE}/subscriptions/{user_id}", json_body=fields)


    def schedule_stream(self, **fields) -> Any:
        if not fields:
            raise ValueError("at least one field required")
        return self.post_json(f"{API_BASE}/streams", json_body=fields)


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

    # /stories takes no vault id, only a convert claim (`send_with` from upload_media).
    def create_story(self, media_files: list, *,
                     caption: str | None = None,
                     mention: str | None = None,
                     question: str | None = None) -> Any:
        send_tripwire.check("create_story")
        body: dict = {
            "mediaFiles": media_files,
            "rfTag": [],
            "rfGuest": [],
            "rfPartner": [],
        }

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
        self._consent(body)

        return self.post_json(f"{API_BASE}/stories", json_body=body)

    def delete_story(self, story_id: int) -> Any:
        return self.delete_json(f"{API_BASE}/stories/{story_id}")

    def post_story(self, file_path: str | Path, *,
                   content_type: str | None = None,
                   watermark_text: str | None = None,
                   caption: str | None = None,
                   mention: str | None = None,
                   question: str | None = None,
                   return_upload: bool = False) -> Any:
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


from of_client import (  # noqa: E402
    API_BASE, OFAPIError, _CoTagRetry, _guard_outbound, _wrap_text_as_p,
    _write_tag_block, log_of,
)
import of_consent  # noqa: E402
from of_rich_text import of_text  # noqa: E402
