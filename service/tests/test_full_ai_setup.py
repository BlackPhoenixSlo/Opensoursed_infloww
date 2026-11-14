#!/usr/bin/env python3
"""test_full_ai_setup — Full AI Chat one-click setup (spec phase-03c).

Persona draft (ticket 52): `POST /admin/full-ai/persona/draft` drafts the Model
info text from her OF name and her existing describe text, and saves nothing.

Seams (spec › Testing Decisions): the LLM faked at the wire
(`llm_client.httpx.AsyncClient`, every request body captured, high cost cap);
OF behind one recording fake at both client factories (`client_pool.get`,
`ax._make_client`; any send raises); the HTTP API through `_harness.make_client()`
sessions on the temp DB; pure table tests for `clean_name`, `clamp_age`,
`us_city`, `scrub`.

  case_clean_name_table             "Kay 🍒 TOP 0.1%" → "Kay"
  case_age_table                    17 → 19, 49 → 49, "twenty" → 22, 140 → 22
  case_city_table                   Austin kept; Toronto / Buenos Aires / Bogota / Paris replaced; stable per account
  case_scrub_table                  explicit clauses dropped, 160-char cut
  case_compose_leaves_out_an_empty_looks_line   no bare `Looks:` reaches the live persona
  case_persona_draft_shape          Name / Age / From / Looks / blank Won't do; explicit item never sent;
                                    no kinks, limits, tattoos; survives compose_persona; 0 OF calls
  case_no_save_until_save           config row byte-identical; grok_calls +1
  case_zero_described_lines         need_describe, text "", 0 wire calls
  case_inputs_read_past_the_first_page  a safe line behind BATCH explicit ones is found
  case_owner_only                   chatter 403 and unowned 403, 0 wire calls
Guards (ticket 53):
  case_wont_do_from_current_text    the textarea's Won't-do line, never the stored one
  case_locked_facts                 stored age / home city / location over the guess; age < 19 → 19 + note
  case_no_name                      no usable OF name → blank Name: + note
  case_cap_and_bad_reply            429 / 502, config row unchanged
Gap describe (ticket 54): the vault describe runs for real (`_describe_and_flag`), vision
faked at the same wire (answered by purpose), Jev at `vault_jev_pass.one`:
  case_gap_describe_fills_the_draft  1 sfw + 5 undescribed → 5 describe calls (never explicit /
                                    removed / clip), then 1 text call holding the new lines;
                                    mirror hit 0 OF calls, miss only CDN fetch + re-sign; up to 6 newest
  case_no_gap_with_three_lines      3 sfw lines → 0 describe calls, 0 OF calls
  case_no_photo_or_every_describe_fails  need_describe, text "", 0 text calls; a vision cap is a 200

Run: ./venv/bin/python service/tests/test_full_ai_setup.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from PIL import Image  # noqa: E402

from sqlalchemy import delete, func, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts  # noqa: E402
import automation_executor as ax  # noqa: E402
import client_pool  # noqa: E402
import full_ai_persona as fp  # noqa: E402
import llm_client  # noqa: E402
import tenant_keys  # noqa: E402
import vault_jev_pass  # noqa: E402
import vault_stills  # noqa: E402
from _jev_fixtures import photo_jev  # noqa: E402
from automations._persona import compose_persona  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountAiConfig, GrokCall, Message, VaultItem, VaultSend  # noqa: E402

IDS = fx.seed_two_agencies()
AID = IDS["creator_a"]           # Agency A's Creator
THEIRS = IDS["creator_b"]        # Agency B's: not Agency A's owner's
OWNER = fx.login_owner("agency_a_owner")
CHATTER = fx.login_chatter("chatter_a")
ROUTE = "/admin/full-ai/persona/draft"
MARKER = "zebracorn"             # only in the explicit item's describe text
T0 = datetime(2026, 11, 1, 12, 0, 0)

asyncio.run(tenant_keys.set_keys(IDS["agency_a_owner"], {"deepseek": "sk-test-agency-a",
                                                           "deepinfra": "di-test-agency-a"}))
# The stills mirror lives in a temp dir (never the relay's /tmp store).
_tmp = Path(tempfile.mkdtemp(prefix="fas_"))
vault_stills.THUMB_DIR, vault_stills.IMAGE_DIR, vault_stills.POSTER_DIR = (
    _tmp / "thumbs", _tmp / "images", _tmp / "posters")
_buf = io.BytesIO()
Image.new("RGB", (60, 80), (200, 150, 120)).save(_buf, format="JPEG")
JPEG = _buf.getvalue()
VISION_MODEL = llm_client.MODELS["qwen3-vl-30b"].api_model


# ── Seams ─────────────────────────────────────────────────────────────

class _Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class Wire:
    """`llm_client.httpx.AsyncClient`: records every request body and answers by
    purpose: a vision describe (the Qwen-VL model) gets a prose describe numbered
    per call, anything else `reply` as the model's message content."""

    bodies: list[dict] = []
    reply: dict | str = {}   # a str is sent as the raw content (a bad reply)
    LOOK = "Auburn ponytail and a denim jacket, look {n}."

    @staticmethod
    def by(purpose: str) -> list[dict]:
        """The captured bodies of one purpose: `describe_media` or `text` (the persona call)."""
        return [b for b in Wire.bodies if (b.get("model") == VISION_MODEL) == (purpose == "describe_media")]

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: A002 — httpx's own kwarg
        Wire.bodies.append(dict(json or {}))
        if (json or {}).get("model") == VISION_MODEL:
            content = _json.dumps({"description": Wire.LOOK.format(n=len(Wire.by("describe_media")))})
        else:
            content = Wire.reply if isinstance(Wire.reply, str) else _json.dumps(Wire.reply)
        return _Resp({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                "prompt_tokens_details": {"cached_tokens": 0}}})


_json = json


class FakeOF:
    """One recording OF client behind both factories: every OF call recorded in
    `calls` (the CDN byte fetch `http.get`, the one-media re-sign
    `vault_media_by_id`, anything else by name); any send recorded in `sends`
    and raised. A stored url (`/stale/`) answers 403, a re-signed one (`/fresh/`)
    the still; `resign=False` makes the re-sign find nothing (a failed fetch)."""

    timeout_s = 5

    def __init__(self, resign: bool = True) -> None:
        self.calls: list[tuple] = []
        self.sends: list[str] = []
        self.resign = resign
        self.http = SimpleNamespace(get=self._cdn_get)

    def _cdn_get(self, url, timeout=None):
        self.calls.append(("http.get", url))
        ok = "/fresh/" in url
        return SimpleNamespace(status_code=200 if ok else 403, headers={}, content=JPEG if ok else b"")

    def vault_media_by_id(self, media_id):
        self.calls.append(("vault_media_by_id", int(media_id)))
        if not self.resign:
            return None
        return {"id": int(media_id), "type": "photo",
                "files": {"preview": {"url": f"https://cdn.example/fresh/{media_id}.jpg"}}}

    def __getattr__(self, name):
        if name.startswith(("send", "post")):
            self.sends.append(name)
            raise AssertionError(f"OF send method {name} called")

        def _call(*_a, **_k):
            self.calls.append((name,))
            return []
        return _call


class Jev:
    """`vault_jev_pass.one`: stamps a current free-lane photo `_jev` (and its flags,
    `_sync_flags`) when `ok`, else answers a failed reading and stamps nothing."""

    calls: list[int] = []
    ok = True

    @staticmethod
    async def one(account_id, media_id, *, sweep=None):
        Jev.calls.append(int(media_id))
        if not Jev.ok:
            return {"media_id": media_id, "ok": False, "status": "error", "detail": "jev down (fake)",
                    "cost_millicents": 0}
        async with get_session() as s:
            item = await s.get(VaultItem, (account_id, media_id))
            f = json.loads(item.ai_fields_json or "{}")
            f["_jev"] = photo_jev("free")
            item.ai_fields_json = json.dumps(f)
            await s.commit()
        await vault_jev_pass._sync_flags(account_id, media_id)
        return {"media_id": media_id, "ok": True, "status": "ok", "lane5": "free", "cost_millicents": 0}


@contextlib.contextmanager
def seams(reply: dict | str, *, jev_ok: bool = True, resign: bool = True):
    Wire.bodies, Wire.reply = [], reply
    Jev.calls, Jev.ok = [], jev_ok
    of, gets, made = FakeOF(resign), [], []
    saved = llm_client.httpx.AsyncClient, client_pool.get, ax._make_client, vault_jev_pass.one
    llm_client.httpx.AsyncClient, vault_jev_pass.one = Wire, Jev.one

    def _get(aid, *a, **k):
        gets.append(aid)
        return of

    def _make(aid, *a, **k):   # building the client is no OF contact (`vault_frames._collect` builds one
        made.append(aid)       # before its disk read), but a draft with no gap builds none
        return of

    client_pool.get, ax._make_client = _get, _make
    try:
        yield SimpleNamespace(of=of, gets=gets, made=made)
    finally:
        llm_client.httpx.AsyncClient, client_pool.get, ax._make_client, vault_jev_pass.one = saved


# ── Seeding ───────────────────────────────────────────────────────────

def _seed_config(aid: str, **kw) -> None:
    async def _go():
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
            if row is None:
                s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=1_000_000, **kw))
            else:
                for k, v in kw.items():
                    setattr(row, k, v)
    asyncio.run(_go())


def _seed_vault(aid: str, items: list[tuple[str | None, str | None]]) -> None:
    """Replace her vault with `items` = [(description, tier)], newest first."""
    async def _go():
        async with get_session() as s:
            await s.execute(delete(VaultItem).where(VaultItem.account_id == aid))
            for i, (desc, tier) in enumerate(items):
                s.add(VaultItem(account_id=aid, media_id=1000 + i, kind="photo", description=desc,
                                explicitness_tier=tier, created_at=T0 - timedelta(minutes=i)))
    asyncio.run(_go())


def _grok_calls(aid: str) -> int:
    async def _go():
        async with get_session() as s:
            return (await s.execute(select(func.count()).select_from(GrokCall)
                                    .where(GrokCall.account_id == aid))).scalar_one()
    return asyncio.run(_go())


def _config_row(aid: str) -> tuple:
    async def _go():
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
            return (row.model_notes, row.persona_facts_json, row.location, row.updated_at)
    return asyncio.run(_go())


SAFE = [("blonde hair, gym outfit, smiling at a beach", "sfw"),
        ("blonde hair, red sundress, coffee shop window seat", "suggestive"),
        ("freckles, oversized hoodie, reading on a couch", "sfw")]
EXPLICIT = (f"nude on the bed, {MARKER} tattoo on hip", "explicit")
MODEL_OUT = {"age": 17, "from": "Paris", "looks": "blonde, naked, nipples visible, freckles",
             "personality": "bubbly, a little shy at first", "likes": "iced coffee, the gym, beach days",
             "kinks": "feet", "limits": "no anal", "tattoos": "rose on wrist"}


def _lines(text: str) -> dict[str, str]:
    out = {}
    for ln in text.splitlines():
        label, _, value = ln.partition(":")
        out[label] = value.strip()
    return out


# ── Pure tables ───────────────────────────────────────────────────────

def case_clean_name_table():
    for raw, want in (("Kay 🍒 TOP 0.1%", "Kay"), ("", ""), ("🍒🍒", ""), (None, "")):
        assert fp.clean_name(raw) == want, (raw, fp.clean_name(raw), want)


def case_age_table():
    for x, want in ((17, 19), (49, 49), ("twenty", 22), (140, 22)):
        assert fp.clamp_age(x) == want, (x, fp.clamp_age(x), want)


def case_city_table():
    assert fp.us_city("Austin", "a1") == "Austin, TX", fp.us_city("Austin", "a1")
    assert fp.us_city("austin, tx", "a1") == "Austin, TX", fp.us_city("austin, tx", "a1")
    for foreign in ("Toronto", "Buenos Aires", "Bogota", "Paris"):
        for aid in ("a1", "a2", "777"):
            got = fp.us_city(foreign, aid)
            assert got in fp.US_CITIES, (foreign, got)
            # The same account always gets the same pick.
            assert got == fp.us_city(foreign, aid) == fp.us_city(None, aid), (foreign, aid, got)
    assert 30 <= len(fp.US_CITIES) <= 50, len(fp.US_CITIES)


def case_scrub_table():
    assert fp.scrub("blonde, naked, nipples visible, freckles") == "blonde, freckles"
    assert fp.scrub("long brown hair; topless by the pool; denim jacket") == "long brown hair, denim jacket"
    assert fp.scrub("bare breasts, green eyes") == "green eyes"
    assert len(fp.scrub("tall, " * 60)) <= 160


# ── The route ─────────────────────────────────────────────────────────

def case_persona_draft_shape():
    accounts.upsert_account(AID, name="Kay 🍒 TOP 0.1%")
    _seed_config(AID, model_notes=None)
    long_desc = "brunette in a yellow raincoat " + "x" * 400
    _seed_vault(AID, [SAFE[0], EXPLICIT, SAFE[1], SAFE[0], SAFE[2], (long_desc, "sfw")])
    with seams(MODEL_OUT) as of:
        r = OWNER.post(ROUTE, json={"account_id": AID, "current_text": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    lines = _lines(body["text"])
    assert lines["Name"] == "Kay", lines
    assert lines["Age"] == "19", lines
    assert lines["From"] in fp.US_CITIES, lines
    assert "blonde" in lines["Looks"] and "freckles" in lines["Looks"], lines
    assert "naked" not in lines["Looks"] and "nipples" not in lines["Looks"], lines
    assert lines["Won't do (hard limits)"] == "", lines
    assert list(lines) == ["Name", "Age", "From", "Looks", "Personality", "Likes", "Won't do (hard limits)"], lines
    low = body["text"].lower()
    for word in ("feet", "anal", "rose on wrist", "kink", "tattoo", "limits:"):
        assert word not in low, (word, body["text"])
    assert not {"kinks", "limits", "tattoos"} & set(body), body
    assert body["need_describe"] is False and body["name"] == "Kay" and body["age"] == 19, body
    assert body["city"] == lines["From"], body
    # The exact duplicate is dropped: 4 distinct safe lines.
    assert body["images_used"] == 4, body

    # One JSON-mode call; what the model saw lacks the explicit item.
    assert len(Wire.bodies) == 1, Wire.bodies
    req = Wire.bodies[0]
    sent = json.dumps(req["messages"])
    assert MARKER not in sent, sent
    assert SAFE[2][0] in sent and "x" * 301 not in sent, sent   # each line cut to 300 chars
    assert req["model"] == "deepseek-v4-flash" and req["temperature"] == 0.4, req
    assert req["response_format"] == {"type": "json_object"}, req
    system = req["messages"][0]["content"]
    for rule in ("Anything the persona already states, COPY EXACTLY.",
                 "You are AUTHORING a persona, not extracting facts about a real person.",
                 "Keep every value SHORT and concrete: a city name, one clause, a plain phrase.",
                 "Prefer a real, ordinary, plausible place a real person would be from.",
                 "Do NOT output a timezone, an offset, or a time — those are computed.",
                 "NEVER output `kinks`, `limits` or `tattoos`",
                 "The city must be in the United States.",
                 "Looks: hair, face, build and clothing style only, from the image notes; never body parts, "
                 "nudity, sex acts or what is visible under clothing.",
                 "Return {age, from, looks, personality, likes}."):
        assert rule in system, (rule, system)

    # The path live Lanes read after Save keeps the Name and Looks lines.
    composed = compose_persona(SimpleNamespace(model_notes=body["text"]), fallback="Ella.")
    assert "Name: Kay" in composed and f"Looks: {lines['Looks']}" in composed, composed

    # OF: no client_pool.get, no OF call of any kind.
    assert of.gets == of.made == of.of.calls == [], (of.gets, of.made, of.of.calls)


def case_compose_leaves_out_an_empty_looks_line():
    got = fp.PersonaInputs(account_id="a1", name_raw="Kay", name="Kay", voice=None, descs=["x"])
    text = fp.compose(got, {"age": 24, "from": "Austin", "looks": "naked, nipples visible"}, "").text
    assert "Looks" not in text, text
    # Every other blank line is an 03a label, so the live composer drops it.
    composed = compose_persona(SimpleNamespace(model_notes=text), fallback="Ella.")
    assert composed.endswith("contradict it):\nName: Kay\nAge: 24\nFrom: Austin, TX"), composed


def case_no_save_until_save():
    stored = "Name: Mia\nAge: 30"
    _seed_config(AID, model_notes=stored, persona_facts_json=json.dumps({"job": "barista"}), location="Ohio")
    _seed_vault(AID, SAFE)
    before, calls = _config_row(AID), _grok_calls(AID)
    with seams(MODEL_OUT):
        r = OWNER.post(ROUTE, json={"account_id": AID, "current_text": stored})
    assert r.status_code == 200, r.text
    assert r.json()["text"] != stored
    assert _config_row(AID) == before, (_config_row(AID), before)
    assert _grok_calls(AID) == calls + 1, (_grok_calls(AID), calls)


def case_zero_described_lines():
    _seed_config(AID, model_notes=None)
    # Undescribed, removed or not-safe items give no line.
    _seed_vault(AID, [(None, "sfw"), ("  ", "sfw"), EXPLICIT, ("lace bodysuit", "hardcore"), ("smiling", None)])
    calls = _grok_calls(AID)
    # The two blank photos are gap candidates (ticket 54); with no Jev reading neither is described.
    with seams(MODEL_OUT, jev_ok=False) as of:
        r = OWNER.post(ROUTE, json={"account_id": AID, "current_text": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["need_describe"] is True and body["text"] == "", body
    assert Wire.bodies == [] and _grok_calls(AID) == calls, Wire.bodies
    assert of.gets == of.made == of.of.calls == [], (of.gets, of.made, of.of.calls)


def case_inputs_read_past_the_first_page():
    # BATCH explicit items newer than the one safe line: the read pages on instead of loading the vault at once.
    _seed_vault(AID, [EXPLICIT] * fp.BATCH + [SAFE[0]])
    got = asyncio.run(fp.inputs(AID))
    assert got.descs == [SAFE[0][0]], got.descs


def case_owner_only():
    _seed_vault(AID, SAFE)
    _seed_vault(THEIRS, SAFE)
    with seams(MODEL_OUT):
        r = CHATTER.post(ROUTE, json={"account_id": AID, "current_text": ""})
        assert r.status_code == 403, r.text
        r = OWNER.post(ROUTE, json={"account_id": THEIRS, "current_text": ""})
        assert r.status_code == 403, r.text
        assert Wire.bodies == [], Wire.bodies



# ── Guards (ticket 53) ────────────────────────────────────────────────

def _draft(current_text: str = "", reply: dict | str = MODEL_OUT):
    with seams(reply) as of:
        r = OWNER.post(ROUTE, json={"account_id": AID, "current_text": current_text})
    assert of.gets == of.made == of.of.calls == [], (of.gets, of.made, of.of.calls)
    return r


def case_wont_do_from_current_text():
    accounts.upsert_account(AID, name="Kay")
    _seed_config(AID, model_notes="Name: Kay\nWon't do (hard limits): meetups, calls", persona_facts_json=None,
                 location=None)
    _seed_vault(AID, SAFE)
    reply = {**MODEL_OUT, "won't do": "anal", "limits": "no anal"}
    r = _draft("Name: Kay\nWon't do (hard limits): no face\nLikes: tea", reply)
    assert r.status_code == 200, r.text
    assert _lines(r.json()["text"])["Won't do (hard limits)"] == "no face", r.json()["text"]
    assert "meetups" not in r.json()["text"] and "anal" not in r.json()["text"], r.json()["text"]
    # No Won't-do line in the box → blank, never invented.
    r = _draft("Name: Kay", reply)
    assert _lines(r.json()["text"])["Won't do (hard limits)"] == "", r.json()["text"]


def case_locked_facts():
    accounts.upsert_account(AID, name="Kay")
    _seed_vault(AID, SAFE)
    _seed_config(AID, model_notes=None, location=None, persona_facts_json=json.dumps({"age": 24, "home_city": "Austin"}))
    r = _draft(reply={**MODEL_OUT, "age": 31, "from": "Denver"})
    assert r.status_code == 200, r.text
    body, lines = r.json(), _lines(r.json()["text"])
    assert lines["Age"] == "24" and lines["From"] == "Austin", lines
    assert body["age"] == 24 and body["city"] == "Austin" and body["notes"] == [], body
    # What the model saw: the stored facts as already confirmed.
    user = json.loads(Wire.bodies[0]["messages"][1]["content"])
    assert user["already_confirmed"] == {"age": 24, "home_city": "Austin"}, user

    _seed_config(AID, persona_facts_json=json.dumps({"age": 18}))
    r = _draft(reply={**MODEL_OUT, "age": 30})
    body, lines = r.json(), _lines(r.json()["text"])
    assert lines["Age"] == "19" and body["age"] == 19, lines
    assert body["notes"] == ["Stored age 18 is under 19; the draft uses 19."], body
    assert "already_confirmed" not in json.loads(Wire.bodies[0]["messages"][1]["content"]), Wire.bodies[0]

    # A stored age with no number counts as unset: the floored guess, never "seventeen".
    _seed_config(AID, persona_facts_json=json.dumps({"age": "seventeen"}))
    r = _draft(reply={**MODEL_OUT, "age": 17})
    assert _lines(r.json()["text"])["Age"] == "19" and r.json()["age"] == 19, r.json()["text"]

    # Stored location with no home city is her From.
    _seed_config(AID, persona_facts_json=None, location="Columbus, Ohio")
    r = _draft(reply={**MODEL_OUT, "from": "Denver"})
    assert _lines(r.json()["text"])["From"] == "Columbus, Ohio", r.json()["text"]
    _seed_config(AID, location=None)


def case_no_name():
    accounts.upsert_account(AID, name="", nickname=f"Account {AID}")
    _seed_config(AID, model_notes=None, persona_facts_json=None, location=None)
    _seed_vault(AID, SAFE)
    r = _draft()
    assert r.status_code == 200, r.text
    body = r.json()
    assert _lines(body["text"])["Name"] == "" and body["name"] == "", body
    assert body["notes"] == ["No OF name stored; type her name."], body
    accounts.upsert_account(AID, name="Kay")


def case_cap_and_bad_reply():
    _seed_vault(AID, SAFE)
    _seed_config(AID, model_notes="Name: Mia", persona_facts_json=json.dumps({"age": 24}), location="Ohio",
                 daily_cost_cap_cents=0)
    before = _config_row(AID)
    r = _draft("Name: Mia")
    assert r.status_code == 429, r.text
    assert Wire.bodies == [], Wire.bodies   # refused before the wire
    assert _config_row(AID) == before, (_config_row(AID), before)

    _seed_config(AID, daily_cost_cap_cents=1_000_000)
    before = _config_row(AID)
    r = _draft("Name: Mia", reply="not json at all")
    assert r.status_code == 502, r.text
    assert len(Wire.bodies) == 1, Wire.bodies
    assert _config_row(AID) == before, (_config_row(AID), before)


# ── Gap describe (ticket 54) ──────────────────────────────────────────

def _seed_gap(aid: str, *, described: int, undescribed: int, mirror: bool, base: int) -> tuple[list[int], list[int]]:
    """Her vault, newest first: a removed blank photo, an `explicit`-tiered blank photo and a blank clip (never
    gap photos; newest, so a sloppy pick takes them), then `undescribed` photos whose stored url is stale (their
    stills on the temp mirror when `mirror`), then `described` sfw items. Returns (gap photo ids newest first,
    the three never-candidates' ids)."""
    raw = lambda mid: json.dumps({"id": mid, "type": "photo",  # noqa: E731
                                  "files": {"preview": {"url": f"https://cdn.example/stale/{mid}.jpg"}}})
    never = [base, base + 1, base + 2]
    gap = [base + 10 + i for i in range(undescribed)]

    async def _go():
        async with get_session() as s:
            await s.execute(delete(VaultItem).where(VaultItem.account_id == aid))
            rows = [dict(media_id=never[0], kind="photo", removed_at=T0),
                    dict(media_id=never[1], kind="photo", explicitness_tier="explicit"),
                    dict(media_id=never[2], kind="video")]
            rows += [dict(media_id=mid, kind="photo") for mid in gap]
            rows += [dict(media_id=base + 50 + i, kind="photo", description=SAFE[i % 3][0] + f" #{i}",
                          explicitness_tier="sfw", describe_status="described") for i in range(described)]
            for i, row in enumerate(rows):
                s.add(VaultItem(account_id=aid, raw_json=raw(row["media_id"]), created_at=T0 - timedelta(minutes=i),
                                **row))
    asyncio.run(_go())
    for mid in gap if mirror else []:
        path = vault_stills.image_path(aid, mid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(JPEG)
    return gap, never


def _rows(aid: str, ids: list[int]) -> dict[int, tuple]:
    async def _go():
        async with get_session() as s:
            return {mid: (it.description, it.explicitness_tier, it.ai_fields_json, it.describe_status)
                    for mid in ids if (it := await s.get(VaultItem, (aid, mid))) is not None}
    return asyncio.run(_go())


def _sends() -> tuple[int, int]:
    async def _go():
        async with get_session() as s:
            return (await s.scalar(select(func.count()).select_from(Message)),
                    await s.scalar(select(func.count()).select_from(VaultSend)))
    return asyncio.run(_go())


def _gap_draft(**kw):
    with seams(MODEL_OUT, **kw) as of:
        r = OWNER.post(ROUTE, json={"account_id": AID, "current_text": ""})
    assert r.status_code == 200, r.text
    assert of.gets == [] and of.of.sends == [], (of.gets, of.of.sends)
    # Client builds only for gap photos: `_collect` builds one, a mirror miss's re-sign one more.
    assert len(of.made) <= 2 * len(Jev.calls), (of.made, Jev.calls)
    return r.json(), of.of


def case_gap_describe_fills_the_draft():
    accounts.upsert_account(AID, name="Kay")
    _seed_config(AID, model_notes=None, persona_facts_json=None, location=None, daily_cost_cap_cents=1_000_000)
    for mirror, base in ((True, 2000), (False, 3000)):
        gap, never = _seed_gap(AID, described=1, undescribed=5, mirror=mirror, base=base)
        cfg, sent = _config_row(AID), _sends()
        body, of = _gap_draft()
        assert sorted(Jev.calls) == sorted(gap), (mirror, Jev.calls, gap)
        assert len(Wire.by("describe_media")) == 5, (mirror, len(Wire.by("describe_media")))
        rows = _rows(AID, gap + never)
        new = [rows[mid][0] for mid in gap]
        assert all(new) and all(rows[mid][1] in fp.SAFE_TIERS for mid in gap), (mirror, rows)
        assert all(rows[mid][:3] == (None, rows[mid][1], None) for mid in never), (mirror, rows)  # never touched
        assert rows[never[1]][1] == "explicit", rows
        # Then 1 persona text call whose request holds the newly described lines.
        text = Wire.by("text")
        assert len(text) == 1, (mirror, len(text))
        notes = json.loads(text[0]["messages"][1]["content"])["image_notes"]
        assert all(d in notes for d in new) and len(notes) == 6, (mirror, notes, new)
        assert body["images_described"] == 5 and body["images_used"] == 6, (mirror, body)
        assert body["need_describe"] is False and body["text"].startswith("Name: Kay"), (mirror, body)
        if mirror:
            assert of.calls == [], of.calls   # a mirror hit makes no OF call of any kind
        else:   # only the CDN fetch + the one-media re-sign, at most one set per gap photo
            assert {c[0] for c in of.calls} <= {"http.get", "vault_media_by_id"}, of.calls
            for mid in gap:
                mine = [c for c in of.calls if str(mid) in str(c[1])]
                assert [c[0] for c in mine] == ["http.get", "vault_media_by_id", "http.get"], (mid, mine)
            assert len(of.calls) == 3 * len(gap), of.calls
        assert _config_row(AID) == cfg, (mirror, _config_row(AID), cfg)
        assert _sends() == sent, (mirror, _sends(), sent)

    # Up to 6 newest undescribed photos.
    gap, _ = _seed_gap(AID, described=0, undescribed=8, mirror=True, base=4000)
    body, of = _gap_draft()
    assert sorted(Jev.calls) == sorted(gap[:6]), (Jev.calls, gap)
    assert len(Wire.by("describe_media")) == 6 and body["images_described"] == 6, body
    assert of.calls == [], of.calls


def case_no_gap_with_three_lines():
    _seed_config(AID, model_notes=None, daily_cost_cap_cents=1_000_000)
    _seed_gap(AID, described=3, undescribed=2, mirror=False, base=5000)
    body, of = _gap_draft()
    assert Wire.by("describe_media") == [] and Jev.calls == [] and of.calls == [], (Jev.calls, of.calls)
    assert len(Wire.by("text")) == 1 and body["images_described"] == 0 and body["images_used"] == 3, body


def case_no_photo_or_every_describe_fails():
    _seed_config(AID, model_notes=None, daily_cost_cap_cents=1_000_000)

    def _empty(body):
        assert body["need_describe"] is True and body["text"] == "" and body["images_described"] == 0, body
        assert Wire.by("text") == [], Wire.by("text")

    # No photo at all (an empty vault), and none that may be described (removed, explicit, a clip).
    for described, base in ((None, 6000), (0, 6100)):
        if described is None:
            _seed_vault(AID, [])
        else:
            _seed_gap(AID, described=0, undescribed=0, mirror=False, base=base)
        body, of = _gap_draft()
        _empty(body)
        assert Wire.bodies == [] and Jev.calls == [] and of.calls == [], (Jev.calls, of.calls)

    # Every gap describe fails: no Jev reading ...
    gap, _ = _seed_gap(AID, described=0, undescribed=3, mirror=True, base=6200)
    body, of = _gap_draft(jev_ok=False)
    _empty(body)
    assert sorted(Jev.calls) == sorted(gap) and Wire.bodies == [], (Jev.calls, len(Wire.bodies))

    # ... the fetch failed (stale url, the re-sign finds nothing) ...
    gap, _ = _seed_gap(AID, described=0, undescribed=3, mirror=False, base=6300)
    body, of = _gap_draft(resign=False)
    _empty(body)
    assert Wire.bodies == [] and len(of.calls) == 2 * len(gap), of.calls
    assert {r[3] for r in _rows(AID, gap).values()} == {"fetch_failed"}, _rows(AID, gap)

    # ... the vision cap: not an error, no call at all ...
    _seed_gap(AID, described=0, undescribed=3, mirror=True, base=6400)
    _seed_config(AID, daily_cost_cap_cents=0)
    body, of = _gap_draft()
    _empty(body)
    assert Wire.bodies == [] and Jev.calls == [], (Jev.calls, Wire.bodies)
    _seed_config(AID, daily_cost_cap_cents=1_000_000)

    # ... or no vision key: the describe preflight refuses before any fetch.
    _seed_gap(AID, described=0, undescribed=3, mirror=True, base=6500)
    asyncio.run(tenant_keys.set_keys(IDS["agency_a_owner"], {"deepinfra": None}))
    try:
        body, of = _gap_draft()
    finally:
        asyncio.run(tenant_keys.set_keys(IDS["agency_a_owner"], {"deepinfra": "di-test-agency-a"}))
    _empty(body)
    assert Wire.bodies == [] and Jev.calls == [] and of.calls == [], (Jev.calls, of.calls)


_harness.run()
