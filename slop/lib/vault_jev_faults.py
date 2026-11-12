"""The vault Jev v8 pass's check names and break-it-once faults (scenarios/2026-11-11-vault-jev-flags.py):
lib/faults.py merges `register(Fault)` into FAULTS. Each patches a product module attribute the product looks up per
call (`_jev_and_flag` by bare name inside `vault_ai_vision`, `vault_describe_jev.route` via the module,
`vault_jev_rules.settle` by bare name inside `final`, `vault_describe_jev.review_lane` by bare name inside `route`;
for videos `vault_frames.collect_jev_video` via the module, `vault_jev_rules.video_targets` / `video_final` via
`rules.`, `vault_frames._jev_frames_sync` / `_publish_scrub` by bare name), so the patch bites on the next press.
JEV_BEFORE_DESCRIBE has no fault of its own any more: a photo described before
Jev has no `_jev` and is skipped, so the order cannot break without the describe checks going red with it.
"""
from __future__ import annotations

JEV_DEFAULT_ON = ("Jev v8 default on: with no setting anywhere, every Creator's photos and clips (bar the planted "
                  "Jev-down ones) end with `_jev` ok; no TypeSafe call and no `_jev` for audio; the describe plan's "
                  "`jev` is {ready, reason} and ready; no `vault_jev_enabled` on the config route or the "
                  "account_ai_config table")
JEV_PHOTO_NO_QWEN_FLAGS = ("Jev v8 default on: no DeepInfra flags call for any photo in either sweep; every photo Jev "
                           "read carries its flags from Jev (`_flags_model` jev, `_flags_v` 3, every flag key)")
JEV_VIDEO_NO_QWEN_FLAGS = ("Jev v8 videos (D54): no DeepInfra flags call for any clip in either sweep; every clip Jev "
                           "read carries its flags from Jev (`_flags_model` jev, `_flags_v` 3, every flag key)")
JEV_VIDEO_FRAMES = ("Jev v8 videos (D54): every clip Jev paid for got pass 1 on exactly its 12 frames (each frame once, "
                    "told apart by colour), and its `_jev` is a video blob (kind video, vv jv1) with 12 frames, each "
                    "with its NudeNet pair and lane")
JEV_VIDEO_TOP3 = ("Jev v8 videos (D54): pass 2 / L ran only on frames whose planted answers ask for it, on "
                  "min(3, that many) of them per clip (5 coin-flip frames -> exactly 3 pass-2 calls), never twice "
                  "on a frame; pass 2 and L each exercised")
JEV_VIDEO_LANE = ("Jev v8 videos (D54): every clip's read lane (`_jev.lane5`, a review clip's `read_lane5`) is the max "
                  "of its frames' planned lanes ($50 off a "
                  "bare-vulva lower crop at frame 6 behind a $10 topless frame 3 and a dressed frame 0; $10 off the "
                  "escalated coin flips; free all dressed) and `_jev.frame` a frame planned at that lane")
JEV_VIDEO_OVER_CAP = ("Jev v8 videos (D54): a clip whose 720p mp4 is over 50 MB is read off its 240p one: the 720p "
                      "GET was answered but not taken, `_jev.src` 240 with `review` over_cap and `bytes` the 240p "
                      "file's, `lane5` review (its read lane under $100), the row disputed (`jev_review`); no "
                      "`files.full` GET for any clip")
JEV_VIDEO_NO_720 = ("Jev v8 videos (D54): a clip OF offers no 720p rendition and no `files.full` for is read off "
                    "its 240p one: "
                    "`_jev.src` 240 with `review` no_720, `lane5` review, the row disputed (`jev_review`); a clip with "
                    "a 720p mp4 under the cap is read off it (`src` 720, no review, `lane5` not review, `bytes` its "
                    "size, not disputed)")
JEV_VIDEO_SCRUB = ("Jev v8 videos (D54): the 720p pass writes the clip's 12 scrub frames (400 px wide) under its 240p "
                   "url's storyboard hash, and the describe reads them: no clip's 240p mp4 is fetched more than its "
                   "Jev read needed (0 when read off the 720p, 1 when off the 240p)")
JEV_PHOTO_NEVER_V2 = ("Jev v8 default on: no photo is ever described with the V2 recipe (no v2 describe call, no "
                      "`_describe` path v2 written this run); a Jev-down photo (TypeSafe 400) ends `_jev` error with "
                      "no describe call and its describe status untouched (skipped, not v2), one Jev "
                      "try per sweep")
JEV_LANES = ("Jev v8: every photo ends `_jev.status` ok with `lane5` the lane its planted answers "
             "spell ($100 inserted, $50 bare vulva / lower crop, $10 topless, free dressed, a coin flip settled), "
             "the fake saw exactly the passes those answers call for (1 / 1+2 / 1+L), `settled` only on the "
             "coin flips; every profile and pass 2 / L exercised; no unplaced, key-less or danger-header-less call")
JEV_BEFORE_DESCRIBE = ("Jev v8: in describe-all, each photo's and clip's TypeSafe calls all happen before its first "
                       "describe call")
JEV_COST = ("Jev v8: each sweep's `jev_cost_millicents` == the fake's billed input tokens at $0.042/M (rounded up per "
            "photo or clip), its `cost_millicents` == DeepInfra billed + that; the account's `typesafe` "
            "grok_daily_cost row and its done `vault_jev_flags` grok_calls rows sum to the same")
JEV_COPY = ("Jev v8: in each planted re-upload photo or clip set one member pays TypeSafe, every other "
            "carries that member's `_jev` with a copy mark and no TypeSafe call of its own")
JEV_DESCRIBE_PROSE = ("Jev-fed describe (D51): every photo Jev did not leave in review is described with "
                      "the prose recipe (no hedge) and stamped `_describe` path prose / px 640 / its `_jev` version; "
                      "its stored description is the fake's prose cut down to exactly the claims its planted answers "
                      "spell (nipples / pussy / inserted), marker kept; each claim both kept and dropped somewhere; "
                      "its `clothing_items` the fake's, and its `over_` garment names from them only over a region "
                      "Jev calls covered")
JEV_DESCRIBE_REVIEW = ("Jev-fed describe (D51): every photo Jev left in review (the coin flips) is "
                       "described with the v6 recipe (V2 + facts + the review hedge) and stamped `_describe` path v6 "
                       "/ px 960; its description is the fake's, unchanged")
JEV_DESCRIBE_VIDEO = ("Jev-fed video describe (D54): every clip Jev read is described with the vid recipe (V2 + the "
                      "clip facts block; the clip hedge iff its `_jev.review` or review lane), on 6 of its scrub frames "
                      "(400 px, its tint), stamped `_describe` path vid with its `_jev` version and no px, the "
                      "fake's description; a Jev-down clip ends `_jev` error with no describe call")
JEV_UI_DESCRIBED = ("Jev v8 UI: Vault Pro on Creator 0, one click on a prose-described photo's tile opens its "
                    "panel, whose Description box settles on the stored Jev-fed text; the row's `_describe.path` is "
                    "prose with Jev flags, and `/admin/vault-ai/items` serves it described with that text and path")
JEV_UI_VIDEO = ("Jev v8 UI: Vault Pro on Creator 0, one click on a vid-described clip's tile opens its panel, whose "
                "Description box settles on the stored text; the row's `_describe.path` is vid with Jev flags, and "
                "`/admin/vault-ai/items` serves it described with that text and path")


def _qwen_flags_too(kind: str) -> None:
    """`kind` items still get the qwen flags call: the flags sweep's per-item step (`vault_ai_vision._jev_and_flag`,
    looked up per call) also sends one qwen flags call after Jev (the retired `_flags_one`, gone since D52/D54:
    the fake's `FLAGS_PROMPT` on the item's still), its spend reported like the real regression would."""
    import json

    import llm_client
    import vault_ai_vision
    import vault_frames
    import vision
    from db.engine import get_session
    from db.models import VaultItem
    try:
        from slop.lib.vault_describe_relay import FLAGS_PROMPT
    except ImportError:  # inside the relay lib/ is on sys.path, not a package
        from vault_describe_relay import FLAGS_PROMPT

    real = vault_ai_vision._jev_and_flag

    async def _jev_and_flag(account_id, media_id, **kw):
        res = await real(account_id, media_id, **kw)
        if await vault_ai_vision._kind(account_id, media_id) != kind:
            return res
        async with get_session() as s:
            item = await s.get(VaultItem, (account_id, media_id))
        got = await vault_frames.collect(account_id, item, json.loads(item.raw_json or "{}"), want=1)
        if not got.images:
            return res
        q = await llm_client.chat(
            model="qwen3-vl-30b", purpose="describe_flags", account_id=account_id, temperature=0.1,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": FLAGS_PROMPT},
                {"type": "image_url", "image_url": {"url": vision.shrink_data_url(got.images[0])}}]}])
        return {**res, "cost_millicents": int(res.get("cost_millicents") or 0) + int(q.cost_cents or 0)}

    vault_ai_vision._jev_and_flag = _jev_and_flag


def _photo_qwen_flags() -> None:
    """Photos still get the qwen flags call (JEV_PHOTO_NO_QWEN_FLAGS)."""
    _qwen_flags_too("photo")


def _video_qwen_flags() -> None:
    """Clips still get the qwen flags call (JEV_VIDEO_NO_QWEN_FLAGS)."""
    _qwen_flags_too("video")


def _video_nine_frames() -> None:
    """Jev reads only a clip's first 9 frames: `vault_frames.collect_jev_video` (looked up per call by
    `vault_jev_pass`) cut to 9 (JEV_VIDEO_FRAMES; the planted frames that set a lane all sit in 0-8, so no lane
    moves)."""
    import vault_frames

    real = vault_frames.collect_jev_video

    async def collect_jev_video(account_id, item):
        got = await real(account_id, item)
        return got._replace(frames=got.frames[:9])

    vault_frames.collect_jev_video = collect_jev_video


def _video_escalate_all() -> None:
    """Pass 2 / L on every frame that asks, not the top 3: `vault_jev_rules.video_targets` (looked up per call by
    `vault_jev.run_video`) with k 12 (JEV_VIDEO_TOP3)."""
    import vault_jev_rules

    real = vault_jev_rules.video_targets
    vault_jev_rules.video_targets = lambda recs, need, k=12: real(recs, need, 12)


def _video_first_frame() -> None:
    """A clip takes its FIRST frame's lane, not its max: `vault_jev_rules.video_final` (looked up per call by
    `vault_jev.run_video`) answers top 0 (JEV_VIDEO_LANE)."""
    import vault_jev_rules

    real = vault_jev_rules.video_final

    def video_final(recs, scores):
        ds, _top = real(recs, scores)
        return ds, 0

    vault_jev_rules.video_final = video_final


def _video_drops_review(why: str) -> None:
    """A clip read off its 240p mp4 for reason `why` is not marked `review`: `vault_frames._jev_frames_sync` (looked
    up by bare name in `_collect_jev_video`) answers review None for it."""
    import vault_frames

    real = vault_frames._jev_frames_sync

    def sync(client, media, dur, deadline):
        got = real(client, media, dur, deadline)
        return got._replace(review=None) if got is not None and got.review == why else got

    vault_frames._jev_frames_sync = sync


def _video_no_scrub() -> None:
    """The 720p pass never publishes its scrub frames: `vault_frames._publish_scrub` (bare name in
    `_jev_frames_sync`) a no-op, so the describe warms the storyboard off another 240p download (JEV_VIDEO_SCRUB)."""
    import vault_frames

    vault_frames._publish_scrub = lambda tmp, h: None


def _video_v2_fallback() -> None:
    """A clip with no Jev reading falls back to today's V2 describe instead of being skipped: `route` answers v2
    where it said skip (JEV_DESCRIBE_VIDEO)."""
    import vault_describe_jev

    real = vault_describe_jev.route

    def route(*, kind, fields):
        path, jev = real(kind=kind, fields=fields)
        return (vault_describe_jev.V2, None) if path is None and kind == "video" else (path, jev)

    vault_describe_jev.route = route


def _photo_v2_fallback() -> None:
    """A photo with no Jev reading falls back to the V2 describe instead of being skipped: `route` answers v2 where
    it said skip (JEV_PHOTO_NEVER_V2)."""
    import vault_describe_jev

    real = vault_describe_jev.route

    def route(*, kind, fields):
        path, jev = real(kind=kind, fields=fields)
        return (vault_describe_jev.V2, None) if path is None and kind == "photo" else (path, jev)

    vault_describe_jev.route = route


def _no_settle() -> None:
    """settle nn.10 blind to NudeNet: a review photo NudeNet sees nothing on settles into a paid lane instead of free
    (JEV_LANES). Still settled, so flags / describe keep reading it (skipping settle outright would leave `review`,
    which no reading maps, and turn the flags + describe checks red with it)."""
    import vault_jev_rules

    real = vault_jev_rules.settle

    def settle(d, mode=vault_jev_rules.SETTLE_MODE):
        had, nn = "nn" in d, d.pop("nn", None)
        real(d, mode)
        if had:
            d["nn"] = nn

    vault_jev_rules.settle = settle


def _describe_ignores_review() -> None:
    """The Jev-fed describe ignores the review lane: `vault_describe_jev.review_lane` (looked up by bare name inside
    `route`) always False, so a review photo gets the prose recipe (JEV_DESCRIBE_REVIEW)."""
    import vault_describe_jev

    vault_describe_jev.review_lane = lambda jev: False


def register(Fault) -> dict:
    return {
        # slop/run vault-jev-flags --break (the scenario's FAULT)
        "photo-still-calls-qwen-flags": Fault(_photo_qwen_flags, (JEV_PHOTO_NO_QWEN_FLAGS,)),
        # slop/run vault-jev-flags --break --fault=photo-describe-falls-back-to-v2
        "photo-describe-falls-back-to-v2": Fault(_photo_v2_fallback, (JEV_PHOTO_NEVER_V2,)),
        # slop/run vault-jev-flags --break --fault=vault-jev-no-settle
        "vault-jev-no-settle": Fault(_no_settle, (JEV_LANES,)),
        # slop/run vault-jev-flags --break --fault=vault-jev-describe-ignores-review
        "vault-jev-describe-ignores-review": Fault(_describe_ignores_review, (JEV_DESCRIBE_REVIEW,)),
        # videos (D54): slop/run vault-jev-flags --break --fault=<name>
        "video-still-calls-qwen-flags": Fault(_video_qwen_flags, (JEV_VIDEO_NO_QWEN_FLAGS,)),
        "video-jev-reads-9-frames": Fault(_video_nine_frames, (JEV_VIDEO_FRAMES,)),
        "video-escalates-every-frame": Fault(_video_escalate_all, (JEV_VIDEO_TOP3,)),
        "video-lane-uses-first-frame": Fault(_video_first_frame, (JEV_VIDEO_LANE,)),
        "video-over-cap-auto-free": Fault(lambda: _video_drops_review("over_cap"), (JEV_VIDEO_OVER_CAP,)),
        "video-missing-720-auto-free": Fault(lambda: _video_drops_review("no_720"), (JEV_VIDEO_NO_720,)),
        "video-scrub-not-published": Fault(_video_no_scrub, (JEV_VIDEO_SCRUB,)),
        "video-describe-falls-back-to-v2": Fault(_video_v2_fallback, (JEV_DESCRIBE_VIDEO,)),
    }
