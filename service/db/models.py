"""
ORM models — the full schema from ARCHITECTURE_PLAN_V2.md §4.

Convention notes (carried throughout):
  • Snake_case column names. Mirrors the SQL in the plan.
  • All UTC timestamps stored as DATETIME with default CURRENT_TIMESTAMP.
    SQLAlchemy maps to Python `datetime` (naive UTC — we never store local).
  • Money in `*_cents` integers (BIGINT for lifetime spend). Never floats.
  • Composite PKs on every per-account-and-X table (chats, messages, fans,
    vault_items, …) so unified queries are `ORDER BY` instead of UNION.
  • JSON-shaped fields (tags, custom_fields, raw_json, recent_events, etc.)
    stored as TEXT and serialized at the application layer. Drizzle/JSONB
    is a Postgres luxury we don't need yet; the relay reads JSON once on
    load and never queries inside.
  • Foreign keys use `ON DELETE CASCADE` where the child only makes sense
    in the context of its parent (sessions → account, list_members → list).
    `ON DELETE SET NULL` where the link is informational (proxies →
    account_id, actions → employee_id).

Every table is plain SQLAlchemy declarative on one shared `metadata`, so
Alembic sees the whole schema.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    case,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
    type_coerce,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# Shared metadata + base. Naming convention so Alembic-generated
# constraint names are stable (otherwise it falls back to anonymous names
# that change across DB engines and break downgrades).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


# ── Reusable defaults ─────────────────────────────────────────────────

def _now() -> datetime:
    """UTC-naive 'now' — kept in one helper so we can swap to UTC-aware
    later without hunting through column defaults."""
    return datetime.utcnow()


# A timestamp that defaults to NOW() at insert time. The `server_default`
# lets the DB fill it for raw-SQL inserts (importer, ad-hoc), while
# `default=_now` covers ORM inserts where the server clock is sometimes
# slightly off the application clock.
def _ts_now() -> Column:
    return mapped_column(
        DateTime, nullable=False, default=_now, server_default=text("CURRENT_TIMESTAMP")
    )


# ── §4.1 Identity / connections ──────────────────────────────────────

class Account(Base):
    """One OF model account. Same row as service/sessions/accounts/<id>/."""
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nickname: Mapped[str | None] = mapped_column(String)
    color: Mapped[str | None] = mapped_column(String)
    proxy_label: Mapped[str | None] = mapped_column(String)  # soft FK → proxies.label
    x_of_rev: Mapped[str | None] = mapped_column(String)
    static_param: Mapped[str | None] = mapped_column(String)
    user_agent: Mapped[str | None] = mapped_column(String)
    is_active_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _ts_now()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class Proxy(Base):
    """Proxy registry — replaces service/proxies.json."""
    __tablename__ = "proxies"

    label: Mapped[str] = mapped_column(String, primary_key=True)
    scheme: Mapped[str] = mapped_column(String, nullable=False)
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String)
    # Encrypted at rest later (phase D). Plaintext for now to match the
    # current proxies.json — flagged in the plan as a known limitation.
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_ip: Mapped[str | None] = mapped_column(String)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    assigned_account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="SET NULL")
    )


class Session(Base):
    """Captured session blobs — replaces session_*.json files."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cookies_json: Mapped[str] = mapped_column(Text, nullable=False)
    x_of_rev: Mapped[str] = mapped_column(String, nullable=False)
    signing_rules_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # Hot path: "give me the active session for account X."
        Index("ix_sessions_account_latest", "account_id", "is_latest"),
    )


class AccountHealth(Base):
    """Per-account OF session health (see service/account_health.py).

    `session_dead_at` set ⇒ OF rejected the stored session ("Wrong user." —
    the creator got logged out / re-linked elsewhere). While set, the
    automation executor skips EVERY run for the account; a periodic
    `client.me()` probe (or a session re-capture) clears it. One row per
    account, created on first flag or deactivation. Soft reference to
    accounts.id — no FK, matching `Account.proxy_label`: the accounts table
    is a mirror of the sessions dir and may lag it.

    `deactivated_at` set ⇒ the owner deactivated the Creator (Creators › ⋮ ›
    Deactivate): its WS pump, ledger polls and automations stop until it is
    activated again, while every listing still shows it. Lives here, not in
    the account's meta.json, because `accounts.upsert_account` rewrites that
    file and would drop the flag."""
    __tablename__ = "account_health"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_dead_at: Mapped[datetime | None] = mapped_column(DateTime)
    session_dead_reason: Mapped[str | None] = mapped_column(String)
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Employee(Base):
    """Your team. No passwords — the picker reads display_name + color.

    `user_id` scopes the roster to one signed-in friend (see
    plan/simple_username_auth_2026_05_24/PLAN.md). NULL = system sentinel
    (e.g. the 'Automation' attribution row); never appears in any user's
    picker. Application-level filtering: every read in employees.py is
    constrained to `user_id == current_user.id`.
    """
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _ts_now()
    user_id: Mapped[str | None] = mapped_column(String, index=True)
    # Set when this Employee is the per-owner mirror of a Chatter (see
    # service/chatters.py + migration 0024_chatter_login). Audit writes
    # under a chatter session resolve (chatter_id, account.owner_user_id)
    # → this row and stamp actions.employee_id. NULL = label-only Employee
    # (legacy, founder-managed). FK is application-level; SQLite ALTER
    # cannot add an inline FK constraint.
    chatter_id: Mapped[str | None] = mapped_column(String, index=True)
    # The Employee's group on the Organization Chart (`employee_groups.id`,
    # docs/spec/phase-05 item 4). NULL = no group. Application-level FK like
    # `chatter_id`; nullable so init_db's ADD-COLUMN catch-up adds it in place.
    group_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        # Partial UNIQUE index — at most one mirror Employee per
        # (chatter, owner) pair. The chatter auto-create path uses
        # ON CONFLICT DO NOTHING against this index, so two simultaneous
        # first-mutations from the same chatter against two new owners
        # don't race-insert duplicate mirror rows. Legacy / label-only
        # Employees (chatter_id IS NULL) are excluded so they can
        # coexist freely with the mirrors. Mirrored in migration
        # 0024_chatter_login for fresh-from-alembic deploys.
        Index(
            "uq_employees_chatter_owner",
            "chatter_id", "user_id",
            unique=True,
            sqlite_where=text("chatter_id IS NOT NULL"),
            postgresql_where=text("chatter_id IS NOT NULL"),
        ),
    )


class EmployeeAccountAccess(Base):
    """Which models can each employee touch. NULL account_id = all models."""
    __tablename__ = "employee_account_access"

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    # nullable + part of PK — represents "any account." SQLite tolerates
    # this via the (employee_id, COALESCE(account_id, '*')) composite-key
    # convention; we enforce uniqueness in code on insert.
    account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )


class Action(Base):
    """Audit log — one row per mutating request, written by middleware."""
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )
    account_id: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String)
    target_id: Mapped[str | None] = mapped_column(String)
    payload_json: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_actions_employee_at", "employee_id", "at"),
        Index("ix_actions_account_at", "account_id", "at"),
    )


class AgencyNotification(Base):
    """One row of an Agency owner's notification centre (service/notifications_api.py):
    an audited action (role changed, employee deactivated, message unsent), a
    missed clock-in or a Creator's dead session. `text` is the sentence the
    panel shows; `data_json` the ids behind it. `dedupe_key` (unique per
    Agency, NULL = none) keeps a sweep from filing one event twice. Unread
    while `read_at` is NULL. Migration 0089_agency_notifications."""
    __tablename__ = "agency_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[str | None] = mapped_column(String)
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )
    data_json: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _ts_now()
    read_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("agency_user_id", "dedupe_key", name="uq_agency_notifications_dedupe"),
        Index("ix_agency_notifications_agency_created", "agency_user_id", "created_at"),
        Index("ix_agency_notifications_created", "created_at"),  # the sweep's retention DELETE
    )


# ── §4.2 Fans (the wide AI-readable table) ───────────────────────────

class Fan(Base):
    """One row per (account, fan). Wide table by design — every field the
    automation pack reads is here so gen_info / followup / welcome_chatter_for_info all
    have a single source. Heavy columns (raw_json) get their own rows in
    sibling tables when they grow."""
    __tablename__ = "fans"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # ── Identity (from OF) ────────────────────────────────────
    of_username: Mapped[str | None] = mapped_column(String)
    of_display_name: Mapped[str | None] = mapped_column(String)
    avatar_url: Mapped[str | None] = mapped_column(Text)

    # ── Our labels ───────────────────────────────────────────
    custom_nickname: Mapped[str | None] = mapped_column(String)
    generated_nickname: Mapped[str | None] = mapped_column(String)
    fan_chosen_nickname: Mapped[str | None] = mapped_column(String)

    # ── AI-extracted facts (Grok fills these) ────────────────
    real_name: Mapped[str | None] = mapped_column(String)
    is_name_real: Mapped[bool] = mapped_column(Boolean, default=True)
    his_age: Mapped[str | None] = mapped_column(String)
    # Fan insights › Profile › "Birthday", as "MM-DD" (no year: Infloww's
    # Birthday trigger fires on the day). Set by hand in the Fan drawer; the
    # Smart Messages Birthday sender (automations/lifecycle_messages) reads it.
    birthday: Mapped[str | None] = mapped_column(String)
    # Fan insights › Profile › Salary, Salary frequency, Last pay date (Infloww's
    # fansConfig fields), set by hand in the Fan drawer so a chatter can time an
    # offer to payday. Salary is free text ("$4k", "60k/yr"); frequency is
    # weekly | biweekly | monthly; last pay date is "YYYY-MM-DD". Nothing else reads them.
    salary: Mapped[str | None] = mapped_column(String)
    salary_frequency: Mapped[str | None] = mapped_column(String)
    last_pay_date: Mapped[str | None] = mapped_column(String)
    home_country: Mapped[str | None] = mapped_column(String)
    home_city: Mapped[str | None] = mapped_column(String)
    hobbies: Mapped[str | None] = mapped_column(Text)
    fetishes: Mapped[str | None] = mapped_column(Text)
    # JSON array of {date, event}
    recent_events: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # DATED timeline, additive/deduped: JSON array [{date, event}] built by gen_info
    # from the real message timestamps. Read by NONE of the six recent_events readers,
    # so the flat string-array shape (and every reader) is left unchanged. NULL == none.
    recent_events_timeline: Mapped[str | None] = mapped_column(Text)
    self_description: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    likes_boobs: Mapped[bool] = mapped_column(Boolean, default=False)
    likes_ass: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str | None] = mapped_column(String)
    # ISO 639-1 language for THIS fan (per-fan override / detection seam). NULL means
    # "use the account default" (resolve_language). language_source is 'manual' when an
    # operator set it (manual always wins over any AI detection). Both nullable — the
    # per-fan UI + gen_info detection ship LATER; the columns exist now so resolve_language
    # and the PATCH guard have a coherent target (no second migration when per-fan lands).
    language: Mapped[str | None] = mapped_column(String)
    language_source: Mapped[str | None] = mapped_column(String)

    # ── §2.4 Extended Grok-extracted facts ───────────────────
    occupation: Mapped[str | None] = mapped_column(Text)
    employer: Mapped[str | None] = mapped_column(Text)
    relationship_status: Mapped[str | None] = mapped_column(Text)
    partner_name: Mapped[str | None] = mapped_column(Text)
    has_kids: Mapped[bool | None] = mapped_column(Boolean)
    # JSON: {partner, kids:[{name,age}], parents:[...], siblings:[...]}
    family_names: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON: [{kind, breed, name}]
    pets: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # ── Mood / stage (Grok + computed) ───────────────────────
    mood_at_last_message: Mapped[str | None] = mapped_column(Text)
    sentiment_trend: Mapped[str | None] = mapped_column(Text)
    relationship_stage: Mapped[str | None] = mapped_column(Text)
    # JSON: {chatty_level, kink_forward, romantic_level, blunt_level}
    communication_style: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # ── Automation pause (human override) ────────────────────
    automation_paused_until: Mapped[datetime | None] = mapped_column(DateTime)

    # ── welcome_chatter_for_info info-gathering: topics we've already asked (V1 QuestionsAsked)
    # JSON list of keys (age/location/hobbies/…); a topic here is never re-asked,
    # so the bot gathers progressively without nagging. NULL == "[]". ──────────
    questions_asked: Mapped[str | None] = mapped_column(Text)

    # ── Persona continuity (what WE told THIS fan) ───────────
    # TIER B — the per-fan claims ledger. What SHE told THIS fan about herself,
    # stored ONLY where it deviates from the account canon (persona_facts_json) or
    # covers something canon didn't. Most fans stay NULL; that is what keeps it
    # cheap. JSON list of {topic, claim, at}, latest-wins per topic, capped at 20
    # (see _common.merge_persona_claims).
    #
    # Why per-fan when canon exists: a claim already made cannot be retracted.
    # Once she has told a fan "estoy acá en Chile", correcting him to Argentina
    # mid-thread is WORSE than staying wrong — he experiences the correction as
    # the lie. Canon keeps new threads right; this keeps existing threads coherent.
    #
    # The three persona_*_claimed scalars below are the fast path for the topics
    # fans ask most; this column carries everything else. Both are already
    # serialized by fans.py and PATCH-editable, so the correction UI is free.
    persona_claims_json: Mapped[str | None] = mapped_column(Text)
    persona_age_claimed: Mapped[str | None] = mapped_column(Text)
    persona_location_claimed: Mapped[str | None] = mapped_column(Text)
    persona_job_claimed: Mapped[str | None] = mapped_column(Text)

    # ── Sync provenance ──────────────────────────────────────
    profile_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    grok_facts_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # ── Notes (may be written back to OF via apply_profiles) ─
    notes: Mapped[str | None] = mapped_column(Text)
    applied_notes: Mapped[str | None] = mapped_column(Text)
    applied_notes_at: Mapped[datetime | None] = mapped_column(DateTime)
    # THE OWED-CUSTOM LEDGER. Set to the moment the qualifying tip landed; NULL
    # means nothing is owed. This column IS the ledger — `_customs.is_owed` reads
    # nothing else.
    #
    # ⚠️ IT USED TO BE A " Custom" SUFFIX ON `custom_nickname`, AND THAT COULD NOT
    # WORK. `custom_nickname` has four other writers, and one of them —
    # `welcome_chatter_for_info._maybe_push_nickname`, reached from ai_chatter on EVERY tick —
    # rebuilds the name from structured facts via `names.build_structured_nickname`,
    # which knows nothing about the marker and therefore drops it. ai_chatter runs
    # every 60s; customs_watch every 900s. So the ledger was erased roughly a minute
    # after it was written, in our DB and on OnlyFans both, and prod confirms it:
    # 204 customs_watch runs, zero fans ever marked. Worse, the in-memory mutation
    # happens BEFORE `_build_messages` reads it, so `_customs.prompt_block` — the
    # "he has paid, stop selling" rule — never rendered once on the engine that
    # closes the sale.
    #
    # A column has no other writers. Nothing about a fan's name can touch it.
    customs_owed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # When an owed CUSTOM was last resolved for this fan (delivered, or cleared
    # by an operator). `customs_watch` ignores tips at or before it.
    #
    # WITHOUT THIS the scanner had no "done" state at all: owed was derived from
    # (a qualifying tip in the window) AND (no marker) AND (no detected
    # delivery), so clearing the marker was indistinguishable from never having
    # marked it — and the next sweep, 15 minutes later, re-marked the same tip.
    # The operator's "Sent" click undid itself on a 72-hour loop.
    #
    # A timestamp rather than a seen-tips table: the fact being recorded is
    # "everything this fan owed up to here is settled", which is one moment, not
    # a set of rows. Nullable, so init_db's additive catch-up adds it in place.
    customs_cleared_at: Mapped[datetime | None] = mapped_column(DateTime)
    # When the gather-close PPV was last ATTEMPTED for this fan. THE RETRY CLOCK,
    # not a receipt: a refusal stamps it too, and that is the whole reason it
    # exists as a column. The graduation fires once and then skip-lists the fan,
    # so it could never storm — but the (since-removed) ai_chatter payer-floor rescue
    # re-evaluated every ~30s tick for as long as he stayed unanswered, and an attempt is a
    # vault read plus a claim LLM call. Unstamped, the 2026-08-23 refusal would
    # have replayed roughly 2,400 times before he wrote again.
    #
    # One writer (`pack_farewell.send_gather_close`) for the same reason
    # `customs_owed_at` above is a column rather than a suffix on a name someone
    # else rewrites. Nullable, so init_db's additive catch-up adds it in place —
    # a NOT-NULL column here would be silently skipped on boot (engine.py:179).
    gather_close_at: Mapped[datetime | None] = mapped_column(DateTime)

    # ── Tags / custom fields ─────────────────────────────────
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    custom_fields: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # ── Behavior counters (denormalized) ─────────────────────
    lifetime_spend_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_likes: Mapped[int | None] = mapped_column(Integer)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    turn_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Timestamps (rebuildable from messages but cached for speed) ─
    last_message_received_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_message_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime)
    subscribed_at: Mapped[datetime | None] = mapped_column(DateTime)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    subscription_status: Mapped[str | None] = mapped_column(String)
    is_followed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # WHEN auto_follow's money gate last READ this fan's profile and found nothing
    # to do — `_classify` said `already_following`. The backfill's progress marker,
    # and deliberately NOT the ping ledger (`FollowPingState`), which means "we
    # fired a notification at him": examining a fan is not notifying him.
    #
    # Without it `_all_stored_fan_ids`'s `ORDER BY last_message_received_at DESC
    # LIMIT headroom` window never advances past an already-followed head: those
    # fans stamped nothing, were excluded by nothing, and re-occupied the head on
    # every tick forever, while the never-messaged tier — which sorts LAST by
    # construction — stayed unreachable at any cap.
    #
    # Nullable/additive: init_db self-heals it via ALTER TABLE (no migration).
    follow_examined_at: Mapped[datetime | None] = mapped_column(DateTime)
    # OF chat-level "Mute notifications" (isMutedNotifications on the /chats item —
    # the creator silenced this chat). Persisted from the scrape; when a muted fan
    # is also a creator we follow (subscribedBy) the automations skip-list them so
    # nobody wastes an LLM call on mutual-promo spam. See _common.should_skip_muted_creator.
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)
    joined_date: Mapped[str | None] = mapped_column(String)

    # ── DEAD COLUMNS: the retired deep_convo drill's state machine ───
    # The engine was removed (2026-08); NOTHING reads or writes these any more.
    # They stay declared because dropping a SQLite column rewrites the whole
    # table, and table-level surgery on the live WAL DB has corrupted prod twice
    # (2026-07-22, 2026-08-09). Removing them is its own deploy with its own
    # backup — never fold it into a code change.
    deep_convo_state: Mapped[str] = mapped_column(String, nullable=False, default="missing")
    deep_convo_skip_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deep_convo_skip_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deep_convo_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    deep_convo_q_text: Mapped[str | None] = mapped_column(Text)
    deep_convo_tease_text: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str] = mapped_column(String, nullable=False, default="onlyfans")
    raw_json: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_fans_last_msg", "account_id", "last_message_received_at"),
        Index("ix_fans_spend", "account_id", "lifetime_spend_cents"),
        Index("ix_fans_relationship_stage", "account_id", "relationship_stage"),
        Index(
            "ix_fans_paused_until",
            "account_id",
            "automation_paused_until",
            sqlite_where=text("automation_paused_until IS NOT NULL"),
            postgresql_where=text("automation_paused_until IS NOT NULL"),
        ),
    )


# ── §4.3 Messages (every word forever) ───────────────────────────────

class Message(Base):
    """One row per OF message. message_id is OF's native id — primary
    dedup key. temp_id is client-generated for optimistic reconcile."""
    __tablename__ = "messages"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)  # 'in' | 'out' | 'system'
    sender_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    media_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # NULL = no PPV at all; False = PPV not yet purchased; True = unlocked.
    is_paid: Mapped[bool | None] = mapped_column(Boolean)
    is_tip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_unsent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unsent_by_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )
    unsent_reason: Mapped[str | None] = mapped_column(Text)
    unsent_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_promise: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    promise_due_date: Mapped[datetime | None] = mapped_column(DateTime)

    sent_by_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )
    temp_id: Mapped[str | None] = mapped_column(String)

    mass_run_id: Mapped[int | None] = mapped_column(Integer)  # FK declared via table_args
    funnel_step: Mapped[int | None] = mapped_column(Integer)
    # Which automation sent this outbound row (welcome_chatter_for_info, send_welcome,
    # followup, autoreply, send_mass_message, reply_mass_funnel,
    # nudge_online, mass_nudge, online_blast; old rows can carry retired
    # kinds). NULL = human send or a legacy
    # pre-0032 row. Distinct from sent_by_employee_id, which lumps every
    # automation under the single system "Automation" sentinel employee.
    automation_kind: Mapped[str | None] = mapped_column(String)

    raw_json: Mapped[str | None] = mapped_column(Text)
    # Qwen3-VL description of an inbound photo the FAN sent. Nothing writes it any
    # more (the inbound describe was removed); rows described before that keep
    # theirs. NULL = never described. The chat engines read it back into history
    # as "[he sent: …]" so the AI can rate / react to it. Added 0052; nullable so
    # init_db's ADD-COLUMN catch-up materializes it on prod with no backfill.
    image_desc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # OF's createdAt
    ingested_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        ForeignKeyConstraint(["mass_run_id"], ["mass_runs.id"], ondelete="SET NULL"),
        # One chat in time order. Its prefix is each fan's history; the rest
        # covers Chatting statistics' reply times (msg_stats.reply_stats, W5
        # 5.1). Replaces ix_messages_account_fan_time (db.engine drops it):
        # init_db adds a missing index by name only.
        Index("ix_messages_chat_seq", "account_id", "fan_id", "created_at", "message_id", "direction",
              "sent_by_employee_id", "mass_run_id", "automation_kind"),
        # Backs the All-Messages tab's wider scan (direction-scoped per
        # account, no fan filter) — see 18_stats_per_fan_csv.md §SQL impact
        # and migration 0017_phase_g_messages_dir_index.
        Index("ix_messages_dir_created", "account_id", "direction", "created_at"),
        # Partial index — only the rows with active temp_ids participate
        # in the reconcile lookup. Tiny on most DBs because rare.
        Index(
            "ix_messages_temp",
            "account_id",
            "temp_id",
            sqlite_where=text("temp_id IS NOT NULL"),
            postgresql_where=text("temp_id IS NOT NULL"),
        ),
        Index(
            "ix_messages_mass",
            "mass_run_id",
            sqlite_where=text("mass_run_id IS NOT NULL"),
            postgresql_where=text("mass_run_id IS NOT NULL"),
        ),
        # Backs the per-automation stats panel (count messages grouped by
        # automation_kind, scoped per account + time). Partial — only
        # automation sends carry a kind.
        Index(
            "ix_messages_automation_kind",
            "account_id",
            "automation_kind",
            "created_at",
            sqlite_where=text("automation_kind IS NOT NULL"),
            postgresql_where=text("automation_kind IS NOT NULL"),
        ),
        # Covers Employee reports' "Messages sent" (msg_stats.chatter_sends, S4):
        # counted per sender off the index alone. Partial — hand-written sends
        # only; the two always-NULL columns are keyed so the index covers the
        # query (SQLite's planner otherwise prefers ix_messages_dir_created).
        Index(
            "ix_messages_chatter_sends",
            "account_id",
            "direction",
            "created_at",
            "sent_by_employee_id",
            "mass_run_id",
            "automation_kind",
            sqlite_where=text("sent_by_employee_id IS NOT NULL AND mass_run_id IS NULL AND automation_kind IS NULL"),
            postgresql_where=text("sent_by_employee_id IS NOT NULL AND mass_run_id IS NULL "
                                  "AND automation_kind IS NULL"),
        ),
    )


# ── Reading messages.created_at when the DATA is dirtier than the SCHEMA ─────
# The column is DateTime NOT NULL, but on 2026-07-22 exactly one row on one
# account held the empty string '' there (an ingest wrote a blank where OF gave
# no createdAt). SQLAlchemy converts a DateTime column while MATERIALISING the
# result, so that single cell raised `ValueError: Invalid isoformat string: ''`
# out of str_to_datetime and took the WHOLE result set down with it — and since
# ai_chatter._gather reads every message of an account in ONE query, one bad cell
# silenced that account's automation completely. Wrapping the consuming `for`
# loop in try/except cannot save it: the raise happens inside .execute()/.all(),
# before the first row is ever handed to the loop.
#
# So a reader that must survive dirty data selects `created_at_text()` instead of
# the mapped column. type_coerce swaps the PYTHON-side type only — the emitted
# SQL is byte-identical, so WHERE/ORDER BY on the real column still work — but the
# DateTime result processor never runs and the driver's raw value comes back
# untouched. `parse_ts()` then converts it, returning None for anything it cannot
# read so the caller can drop that ONE row (with a warning) instead of the account.
def created_at_text():
    """`Message.created_at` selected WITHOUT the DateTime parse (see above)."""
    return type_coerce(Message.created_at, String).label("created_at")


def parse_ts(value) -> datetime | None:
    """Best-effort DB timestamp → naive-UTC datetime; None when unusable.

    Tolerates what the DateTime processor refuses: '', whitespace, a stray 'Z',
    junk. Returns naive UTC because that is what the rest of the schema stores —
    an aware datetime leaking out of here would blow up the very arithmetic
    (`utcnow() - ts`) the callers do with it.
    """
    if value is None or isinstance(value, datetime):
        return value                      # None, or a driver that types it for us
    s = str(value).strip()
    if not s:
        return None                       # the '' cell that started all this
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class MessageMedia(Base):
    """One row per media item attached to a message — the render-stability
    cache (18_chat_render_stability.md §1.1). width/height start NULL and are
    populated lazily: by T-API from the OF REST /chats/{id}/messages media
    `files`/`info`, and/or by a client onload→PATCH for items OF didn't size.
    The skeleton box must never depend on dims existing; raw_json carries only
    the media id (not dimensions), so there is NO raw_json backfill path."""
    __tablename__ = "message_media"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str | None] = mapped_column(String)  # photo | video | gif | audio
    width: Mapped[int | None] = mapped_column(Integer)   # NULLABLE — see docstring
    height: Mapped[int | None] = mapped_column(Integer)  # NULLABLE — see docstring
    thumb_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)  # video/audio length
    ingested_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        # Child of messages — the dims/media cache only makes sense per
        # message, so cascade-delete with the parent (incl. when a mass
        # placeholder row is reconciled away).
        ForeignKeyConstraint(
            ["account_id", "fan_id", "message_id"],
            ["messages.account_id", "messages.fan_id", "messages.message_id"],
            ondelete="CASCADE",
        ),
        # The client dims-PATCH and any per-media lookup go by media_id.
        Index("ix_message_media_media", "account_id", "media_id"),
    )


class ScrapeHistory(Base):
    """Last-seen-message fast-skip — ported verbatim from the automation pack."""
    __tablename__ = "scrape_history"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_message_text: Mapped[str | None] = mapped_column(Text)
    last_scrape_at: Mapped[datetime] = _ts_now()


# ── §4.4 Transactions (split for fast spend queries) ─────────────────

class Transaction(Base):
    """Every PPV unlock, tip, subscription, rebill, custom. Separate
    table so 'lifetime spend by fan' and 'revenue by day' are single
    index scans instead of message aggregates."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    # OF user id. Ledger rows carry it for every kind, rebills included (the
    # payouts row names its fan: 0 NULL in 515 rebills, 2026-10 snapshot);
    # NULL only when a source row names no fan.
    fan_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Written only by the Fansly ingest (its source row is the sole audit copy:
    # the notification scrolls off). OF ledger rows (~1.5 KB, which OF serves
    # again on demand) and WS-pump rows (a copy of the frame, up to 64 KB)
    # leave it NULL: nothing reads it, and it was most of each row's width.
    # Older OF rows still carry theirs; a NULL-out narrows pages only after a
    # VACUUM.
    raw_json: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = _ts_now()

    # Phase F (0013_phase_f_transaction_ingest): OF payouts/transactions
    # ledger fields. `source` distinguishes WS-pump rows (provider_id
    # NULL) from ingest-written rows (provider_id set). `status` is a
    # soft string — stats filter `WHERE status='cleared'` is the contract.
    provider_transaction_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'cleared'")
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime)
    payout_pending_days: Mapped[int | None] = mapped_column(Integer)
    net_cents: Mapped[int | None] = mapped_column(Integer)
    fee_cents: Mapped[int | None] = mapped_column(Integer)
    vat_cents: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'ws'")
    )

    # 0015: manual override for the attribution view's COALESCE. Set via
    # POST /admin/ingest/transactions/{id}/attribute when ops want a tip
    # (or any tx) to count toward a specific employee, bypassing the
    # 7-day-lookback heuristic.
    attributed_employee_id: Mapped[int | None] = mapped_column(Integer)

    # 0077: the attribution view's answer for this row, materialised at write
    # time by SQLite triggers (tx_rollup.py): the credited Employee (the manual
    # override above, else the linked message's sender, else for a standalone
    # tip the 7-day lookback's), the `rule` that chose it (`manual`, `message`,
    # `tip_lookback`, `unassigned`) and the crediting message's
    # `automation_kind`. Never written by Python.
    credit_employee_id: Mapped[int | None] = mapped_column(Integer)
    credit_rule: Mapped[str | None] = mapped_column(String(16))
    credit_automation_kind: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_tx_account_time", "account_id", "occurred_at"),
        Index(
            "ix_tx_fan_time",
            "account_id",
            "fan_id",
            "occurred_at",
            sqlite_where=text("fan_id IS NOT NULL"),
            postgresql_where=text("fan_id IS NOT NULL"),
        ),
        Index("ix_tx_kind", "account_id", "kind", "occurred_at"),
        # Phase F: partial unique on the OF hash id so re-polls of the
        # same ledger row hit ON CONFLICT DO UPDATE (handles loading→cleared).
        # WS-pump rows (NULL provider_id) skip uniqueness via the partial WHERE.
        Index(
            "uq_tx_provider_id",
            "account_id",
            "provider_transaction_id",
            unique=True,
            sqlite_where=text("provider_transaction_id IS NOT NULL"),
            postgresql_where=text("provider_transaction_id IS NOT NULL"),
        ),
        # Leading column is `status` (not account_id) because the pending_q
        # in /admin/stats/per-model filters status != 'cleared' WITHOUT an
        # account_id equality (cross-account aggregate).
        Index("ix_tx_status_occurred", "status", "occurred_at"),
        # Phase F (0014): cross-writer dedup target. WS pump and the
        # Phase F PPV writer race for the same (account, fan, message_id)
        # — partial-unique lets ON CONFLICT promote ppv_pending → ppv_message.
        # `kind` deliberately excluded from the key (see migration docstring).
        Index(
            "uq_tx_msg",
            "account_id",
            "fan_id",
            "message_id",
            unique=True,
            sqlite_where=text("message_id IS NOT NULL"),
            postgresql_where=text("message_id IS NOT NULL"),
        ),
    )


# ── §4.5 Vault / Posts / Chats / Lists ──────────────────────────────

class Chat(Base):
    """One row per conversation = (account, fan). Hot-read for the inbox list."""
    __tablename__ = "chats"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_message_preview: Mapped[str | None] = mapped_column(Text)
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hidden_locally: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    list_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    preview_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        # Powers the unified-inbox ORDER BY.
        Index("ix_chats_last_msg", "last_message_at"),
    )


class VaultItem(Base):
    """OF vault mirror + our metadata."""
    __tablename__ = "vault_items"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)

    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    thumb_url: Mapped[str | None] = mapped_column(Text)
    full_url: Mapped[str | None] = mapped_column(Text)
    folder_id: Mapped[int | None] = mapped_column(BigInteger)

    description: Mapped[str | None] = mapped_column(Text)
    suggested_price_cents: Mapped[int | None] = mapped_column(Integer)
    default_price_cents: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notes: Mapped[str | None] = mapped_column(Text)
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    raw_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # ── Vault-AI mirror + describe layer (added 0046) ──────────────
    # All nullable so init_db's boot ADD-COLUMN catch-up applies them on a
    # create_all-built DB whose alembic_version lags (house convention).
    #
    # Cache/mirror bookkeeping. `search_text` is the denormalised, lower-cased
    # blob (tags + description + video_description + notes) we LIKE-scan for
    # instant LOCAL search once the vault is collected. `of_folder_ids` is a
    # JSON int array of the OF vault-list ids this item belongs to (filled by
    # the per-folder pass) so folder filtering is local too. `updated_at_of`
    # holds OF's own updatedAt when present; `last_seen_run_id` is bumped every
    # collect sweep so a vanished item can be soft-deleted after two clean runs.
    search_text: Mapped[str | None] = mapped_column(Text)
    # OF-search terms this item matched (harvested from OF's own vault search so
    # our local search is a superset of OF's). Folded into search_text too.
    of_terms: Mapped[str | None] = mapped_column(Text)
    of_folder_ids: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String)
    content_hash_kind: Mapped[str | None] = mapped_column(String)
    updated_at_of: Mapped[str | None] = mapped_column(String)
    last_seen_run_id: Mapped[int | None] = mapped_column(BigInteger)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Per-folder manual ordering. Signed: 0 = absolute first, 1,2,3… pinned
    # from the front, -1 = absolute last, -2,-3… from the back; NULL = normal
    # sort. Toggled per folder in the UI.
    manual_order: Mapped[int | None] = mapped_column(Integer)

    # AI describe output (Qwen3-VL). Effective value = locked override >
    # override > AI field > legacy column; operator edits win and lock.
    video_description: Mapped[str | None] = mapped_column(Text)
    explicitness_tier: Mapped[str | None] = mapped_column(String)
    story_suitable: Mapped[bool | None] = mapped_column(Boolean)
    # AI rank 0-100 pairing story_suitable (feat 6); nothing scores it since
    # its producer was retired, so it is NULL unless set by hand. Effective value still flows through operator override/lock.
    story_score: Mapped[int | None] = mapped_column(Integer)
    tip_vault_flag: Mapped[bool | None] = mapped_column(Boolean)
    # AI rank 0-100 pairing tip_vault_flag (feat 5); NULL until scored.
    tip_vault_score: Mapped[int | None] = mapped_column(Integer)
    suggested_caption: Mapped[str | None] = mapped_column(Text)
    suggested_script: Mapped[str | None] = mapped_column(Text)
    describe_status: Mapped[str | None] = mapped_column(String)
    describe_generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    describe_model: Mapped[str | None] = mapped_column(String)
    describe_call_id: Mapped[int | None] = mapped_column(BigInteger)
    frames_sampled: Mapped[int | None] = mapped_column(Integer)
    ai_fields_json: Mapped[str | None] = mapped_column(Text)
    operator_overrides_json: Mapped[str | None] = mapped_column(Text)
    locked_fields_json: Mapped[str | None] = mapped_column(Text)
    review_state: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String)

    # RETIRED: script_id, script_seq, script_score, script_reversed (the deleted
    # upload-burst orientation pass wrote them) and their index
    # ix_vault_account_script stay on older databases, unmapped. All nullable.

    __table_args__ = (
        Index("ix_vault_account_created", "account_id", "created_at"),
        Index("ix_vault_account_send", "account_id", "send_count"),
        Index("ix_vault_account_seen", "account_id", "last_seen_run_id"),
        Index("ix_vault_account_describe", "account_id", "describe_status"),
    )


class VaultCacheRun(Base):
    """One "Collect all" sweep of the OF vault into the `vault_items` mirror.

    Drives the button's progress UI and gives soft-delete the "two clean
    sweeps agreed" guard (trap 4): only items whose `last_seen_run_id` lags
    two completed runs are candidates for removal, so a mid-upload page shift
    can't false-delete. `status` ∈ running|done|error|canceled.
    """
    __tablename__ = "vault_cache_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    phase: Mapped[str | None] = mapped_column(String)
    total_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = _ts_now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("ix_vault_cache_runs_account", "account_id", "started_at"),)


class VaultFolder(Base):
    """An INTERNAL vault folder (our own, not OF's vault-list). Lets the
    operator organize the mirror — new folder, select media, add to folder,
    reorder — with zero OF writes (OF-mirror is a separate, later concern).
    `of_list_id` is NULL until/unless the folder is mirrored to OF.
    """
    __tablename__ = "vault_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    of_list_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[str] = mapped_column(String, nullable=False, default="operator")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (Index("ix_vault_folders_account", "account_id", "deleted_at"),)


class VaultFolderItem(Base):
    """Membership of a media item in an INTERNAL vault folder, with a
    per-folder `manual_order` (0 = first, 1,2,3… from front, -1 = last,
    -2,-3… from back, NULL = normal order) so videos can be ordered inside a
    folder independently of the global vault order."""
    __tablename__ = "vault_folder_items"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    folder_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    manual_order: Mapped[int | None] = mapped_column(Integer)
    added_at: Mapped[datetime] = _ts_now()

    __table_args__ = (Index("ix_vault_folder_items_folder", "account_id", "folder_id"),)


class VaultOfQueryLog(Base):
    """Which OF vault-search queries we've already harvested (so we don't re-hit
    OF every keystroke). TTL'd; on a fresh hit the terms already live in each
    matched item's `of_terms`/`search_text`, so the local search is instant."""
    __tablename__ = "vault_of_query_log"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    query: Mapped[str] = mapped_column(String, primary_key=True)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_at: Mapped[datetime] = _ts_now()


class VaultResponseCache(Base):
    """Shared server-side cache for the OF vault listing endpoints.

    Every employee on the same OF account sees the same vault, so the
    first picker-open warms the cache for everyone else. Read path checks
    `fetched_at` against a configurable TTL; any vault-mutating call
    (upload, delete, folder edit) wipes every row for the account so the
    next read goes upstream.

    `query_key` packs the full request shape (`type=…|list=…|offset=…|limit=…`
    or `lists:view=…|limit=…|offset=…`) so each (account, params) tuple
    has its own slot — pagination pages cache independently.
    """
    __tablename__ = "vault_response_cache"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    query_key: Mapped[str] = mapped_column(String, primary_key=True)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, server_default=text("CURRENT_TIMESTAMP"),
    )


class SavedReply(Base):
    """Local-only saved replies (a.k.a. "templates" minus the welcome slot).

    OF's API rejects creates against `/messages/templates` for everything
    except `template=reply_on_subscribe`, so we keep saved replies in our
    own DB and never round-trip them through OF. The welcome message
    stays on OF.

    `media_json` is a serialized array of vault-media references
    (`[{id, type, files?}]`) so the editor can re-render thumbs without
    a second fetch. We don't FK to vault_items because the media may
    not have been imported yet on first edit. """
    __tablename__ = "saved_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String)   # short label for the picker
    text: Mapped[str] = mapped_column(Text, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    media_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # OF user ids of creators to @-tag when this template fires. Picker
    # in the editor enforces validity — empty array means "no tagging".
    tagged_users_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Vault-media ids inside `media_json` that ride along UNLOCKED when
    # `price_cents > 0`. Empty array means "everything PPV-locked".
    previews_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Optional Giphy id; when set, picking this template seeds the composer's
    # picked-GIF state so the GIF is sent alongside. NULL = no GIF.
    gif_id: Mapped[str | None] = mapped_column(String)
    # Cached animated preview URL — lets the editor and picker render the
    # GIF chip without a fresh Giphy roundtrip.
    gif_url: Mapped[str | None] = mapped_column(Text)
    # Optional script grouping. When both are set, sending this template in
    # a chat advances a per-chat cursor; the composer then surfaces the
    # template with the next `script_step` (same `script_id`) as a one-tap
    # suggestion bubble. NULL on either field opts the template out.
    script_id: Mapped[str | None] = mapped_column(String)
    script_step: Mapped[int | None] = mapped_column(Integer)
    # Growth > Scripts' tags: a JSON array of tag names. A tag exists while
    # some script carries it (no tags table). NULL reads as [].
    tags_json: Mapped[str | None] = mapped_column(Text)
    # Growth > Scripts' internal notes (chatter-facing, never sent).
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_saved_replies_account", "account_id", "updated_at"),
    )


class VaultSend(Base):
    """Per-fan send history. Powers 'remember new price' + analytics."""
    __tablename__ = "vault_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    fan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = _ts_now()
    was_purchased: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        Index("ix_vault_sends_fan", "account_id", "fan_id", "sent_at"),
        Index("ix_vault_sends_media", "account_id", "media_id", "sent_at"),
    )


class PurchaseFollowupClaim(Base):
    """One row per purchase the purchase_followup automation has claimed — its
    at-most-one-message-per-purchase guard.

    PK is (account_id, fan_id, purchased_message_id): a purchase is one fan
    unlocking one priced message. The fan is in the key because the messages
    table's own key is (account, fan, message) — a mass PPV's placeholder id is
    shared by every recipient — so a message id alone would let one buyer's claim
    swallow another's. An INSERT … ON CONFLICT DO NOTHING that changes no row
    means the purchase was already claimed. Written BEFORE the send and only
    deleted when OnlyFans provably created nothing (a rate-limit refusal). Its own
    table, not `fans.custom_fields`, because other writers rewrite that blob whole
    and would erase a claim. `init_db`'s create_all makes it.

    `silent` marks a purchase claimed WITHOUT a message, because the fan was
    already thanked within the day; only non-silent claims count as a thank-you."""
    __tablename__ = "purchase_followup_claims"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    purchased_message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    silent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                         server_default=text("0"))
    created_at: Mapped[datetime] = _ts_now()


class PurchaseNotice(Base):
    """When OnlyFans' purchases feed says a fan bought a message: the
    notification's own `createdAt` (naive UTC), written by purchase_notifications
    for every notification that carries one, whether or not it flipped the row
    (another writer may have flipped it first). purchase_followup reads it as
    proof of WHEN a fan bought: `messages.purchased_at` is restamped "now" by
    other writers. Its own small table, so the sweep reads it by its
    (account_id, notified_at) index instead of scanning `messages`."""
    __tablename__ = "purchase_notices"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_purchase_notices_time", "account_id", "notified_at"),
    )


class Post(Base):
    """Draft / scheduled / posted / failed — the post timeline."""
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    of_post_id: Mapped[int | None] = mapped_column(BigInteger)
    temp_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    label_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_reason: Mapped[str | None] = mapped_column(Text)
    excluded_list_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_by_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )
    raw_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_posts_account_status", "account_id", "status", "scheduled_for"),
    )


class List(Base):
    """OF list / our local list. kind drives behavior:
       regular            — mirrors an OF list
       exclude            — automatic skip in mass DM
       hidden             — drop from default inbox
       post_label         — labels on profile posts
       smart              — saved query (query_json)
       automation_include — the include-only automation audience mirror: a local
                            snapshot of ONE operator-picked OF folder
                            (of_list_id), reconciled OF→local by the retired
                            `audience_sync` automation. `list_members` under
                            this row is the gate-time read for every gated
                            engine (no OF round-trip at send time).
       autofence          — the per-account AUTOFENCE system list: ONE stable
                            OF list id holding (sendable universe − include
                            members), attached to enforce-mode broadcasts via
                            `excludedLists`. Membership lives OF-side; the row
                            pins the stable id + fence health in sync_meta_json."""
    __tablename__ = "lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    of_list_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    query_json: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Audience runtime state (automation_include / autofence rows only).
    # Last COMPLETE successful OF→local reconcile; NULL = never synced, and the
    # audience resolver treats an enforce-mode account whose mirror has never
    # synced as still-in-shadow rather than darkening the roster.
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Free-shape RUNTIME state (scan generations, baseline readiness, truncation,
    # fence health, kill-switch pause). Deliberately NOT in a validated config
    # blob: config validators are strict allowlists that silently drop unknown
    # keys, which is exactly the fail-open trap runtime state must not sit behind.
    sync_meta_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()


class ListMember(Base):
    __tablename__ = "list_members"

    list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lists.id", ondelete="CASCADE"), primary_key=True
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = _ts_now()
    added_by_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )


# ── §4.6 AI / automation tables ─────────────────────────────────────

class FanProfile(Base):
    """Grok-generated profile. Linked back to the grok_calls row that produced it."""
    __tablename__ = "fan_profiles"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    original_name: Mapped[str | None] = mapped_column(String)
    message_count_at_gen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_spend_at_gen_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nickname: Mapped[str | None] = mapped_column(String)
    short_bio: Mapped[str | None] = mapped_column(Text)
    bullet_points: Mapped[str | None] = mapped_column(Text)
    q1: Mapped[str | None] = mapped_column(Text)
    q2: Mapped[str | None] = mapped_column(Text)
    q3: Mapped[str | None] = mapped_column(Text)
    tease1: Mapped[str | None] = mapped_column(Text)
    tease2: Mapped[str | None] = mapped_column(Text)
    tease3: Mapped[str | None] = mapped_column(Text)
    applied_notes: Mapped[str | None] = mapped_column(Text)
    notes_applied_successfully: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_applied_nickname: Mapped[str | None] = mapped_column(String)
    last_applied_notes: Mapped[str | None] = mapped_column(Text)
    last_generated_at: Mapped[datetime] = _ts_now()
    # Cross-reference to the prompt that generated this profile + the call audit row.
    generated_by_grok_call_id: Mapped[int | None] = mapped_column(Integer)


class FollowupState(Base):
    """Drip state machine — 26h → 64h → 256h thresholds (automation pack §07)."""
    __tablename__ = "followup_state"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    phase: Mapped[str] = mapped_column(String, nullable=False, default="tracking")
    cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    silence_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    fan_last_reply_at: Mapped[datetime | None] = mapped_column(DateTime)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime)
    messages_sent: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = _ts_now()


class WelcomeSent(Base):
    """Dedup welcome-message sends per fan."""
    __tablename__ = "welcome_sent"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fan_username: Mapped[str | None] = mapped_column(String)
    sent_at: Mapped[datetime] = _ts_now()


class SkipList(Base):
    """Per-account 'don't auto-reply' list."""
    __tablename__ = "skip_list"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str | None] = mapped_column(String)
    added_at: Mapped[datetime] = _ts_now()


class Blacklist(Base):
    """Global ban — applies across every model."""
    __tablename__ = "blacklist"

    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str | None] = mapped_column(String)
    added_at: Mapped[datetime] = _ts_now()


class AccountAiConfig(Base):
    """Per-model AI voice + caps. Persona + time_activities used by welcome/followup."""
    __tablename__ = "account_ai_config"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    persona: Mapped[str | None] = mapped_column(Text)
    welcome_rules: Mapped[str | None] = mapped_column(Text)
    utc_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # IANA zone ("America/New_York") for Human Rhythm's sleep window. DST-correct,
    # unlike utc_offset — which stays the fallback when this is NULL, so an account
    # that already set an offset doesn't have to re-answer. Neither set ⇒ rhythm
    # stays disabled rather than defaulting to UTC: a UTC default would put a US
    # creator to sleep through her peak earning window and nothing would explain
    # the revenue drop. See service/automations/rhythm.py:local_now.
    timezone: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    # STRUCTURED creator facts — the canon she must never contradict, pinned into
    # every chat prompt above the free-text persona. JSON dict, all keys optional.
    # The key set is owned by _common.PERSONA_FACT_FIELDS (a save-path allowlist,
    # so an unknown key is dropped rather than stored) and is driven by what fans
    # measurably ask: relationship, age, kids, location, name, family, job ...
    #
    # Why this exists as fields and not more prose: `persona` averaged 202-882
    # chars across live accounts while the style scaffolding around it ran ~5,000,
    # and the gaps were exactly what fans probe. Ellafree's persona said "Born and
    # raised in Argentina" with NO city — so when a fan asked where she grew up the
    # model improvised, and a 966-turn thread walked Argentina → Chile → Córdoba
    # before the fan said "ya no creo nada". A named empty slot is what the enrich
    # button fills; free prose has no slots to notice are missing.
    #
    # Empty/absent keys render NOTHING (byte-identical prompt), same discipline as
    # the clock and location blocks. Nullable, no server_default: init_db's
    # ADD-COLUMN catch-up materializes it on prod with no backfill.
    persona_facts_json: Mapped[str | None] = mapped_column(Text)
    # My Automations › Get to know fans' "Model info": a SHORT free-text note
    # anyone with access to the account may edit (chatters included), pinned into
    # every chat prompt by _persona.compose_persona. The editor prefills
    # _persona.MODEL_NOTES_TEMPLATE; its untouched label lines render nothing.
    # Nullable, no server_default: NULL == no notes, a byte-identical prompt.
    model_notes: Mapped[str | None] = mapped_column(Text)
    # ISO 639-1 language this creator writes in (en/es/sl/…). NULL == "en". Gates BOTH
    # the output language of every conversational prompt AND which guard vocabulary
    # runs (English-only guards would mangle Spanish, and vice-versa — see
    # resolve_language + the Spanish guard layer). Nullable, no server_default: NULL is
    # treated as "en" in code, so init_db materializes it on prod with zero risk.
    language: Mapped[str | None] = mapped_column(String)
    # Whose voice this account writes in: NULL/'her' == a female creator (every
    # account that has ever run here), 'him' == the male lane. Same shape and same
    # reasoning as `language` directly above: nullable, no server_default, and
    # normalised in code (automations/_voice.norm_voice) rather than by a CHECK or
    # an enum — a corrupt value must degrade to the shipped lane, never raise on a
    # send path. NULL keeps every existing account byte-identical, which is the
    # whole safety argument for a second lane and is asserted in test_voice_lane.
    voice: Mapped[str | None] = mapped_column(String)
    # JSON dict {morning_1, morning_2, afternoon_1, afternoon_2, evening, night}
    time_activities_json: Mapped[str | None] = mapped_column(Text)
    # TODAY's generated day, overwritten each creator-local date (automations/_daylog):
    # {"date","weekday","beats":[{id,slot,text}],"covers":[{id,kind,text}]}. The six
    # slots above are its TONE SEED, not its content — read literally they are the
    # same day forever, which is a schedule rather than a life. NULL == no day log,
    # and every renderer returns "" for it, so an un-generated account produces a
    # byte-identical chat prompt. Only today is kept: nothing reads yesterday, and a
    # growing history in a config column is how grok_calls became 52% of the DB.
    day_log_json: Mapped[str | None] = mapped_column(Text)
    # Parallel per-slot vault image IDs, same 6 keys → media_id (int). When set,
    # welcome/followup attach the configured image for the current slot directly
    # (no vault-folder lookup). A future templates UI writes this. NULL → fall
    # back to the legacy folder picker. e.g. {"morning_1": 3666527793, ...}
    time_images_json: Mapped[str | None] = mapped_column(Text)
    # Operator-approved FIXED welcome activity line per slot (the "pin" from the
    # Brain preview: send_welcome sends that exact line instead of the slot's
    # template line). JSON dict
    # {slot_key: {"line": str, "weekday": str}} — the stored weekday is swapped to
    # the current day at send so a daily welcome never says the wrong weekday. NULL /
    # missing slot → the template line. e.g. {"afternoon_1": {"line": "just got back
    # from the beach, Thursday arvo in Argentina lol", "weekday": "Thursday"}}
    welcome_pinned_json: Mapped[str | None] = mapped_column(Text)
    daily_cost_cap_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Per-account LLM model override. NULL (or an id no longer in MODELS) →
    # `_common.DEFAULT_MODEL` via resolve_model. See 19 §4.
    model: Mapped[str | None] = mapped_column(String)
    # Optional per-purpose override, JSON e.g. {"gen_info":"deepseek-v4-flash",
    # "welcome_chatter_for_info":"deepseek-v4-pro"}. NULL → use `model` for all.
    model_by_purpose: Mapped[str | None] = mapped_column(Text)
    # How hard a REASONING model may think, for the account's picked model
    # ("low"/"medium"/"high"/"max" — the legal set is per provider, so the Brain
    # editor offers only what the current model accepts). NULL → use the
    # model's own pin, which is the right answer for almost every account.
    #
    # Deliberately NOT per purpose. The value is a property of the model an
    # operator picked, and `model_by_purpose` can name models on two different
    # providers whose legal sets do not overlap; a per-purpose effort would let
    # one be saved against the other. A value that no longer fits the resolved
    # model is dropped in llm_client._resolve_effort rather than raised on.
    reasoning_effort: Mapped[str | None] = mapped_column(String)
    # nudge_online (P4): per-account config for the "message a fan when they come
    # online" automation — JSON {enabled, nudge_line_text, nudge_line_image, repeat_mode, delay_minutes,
    # jitter_minutes, gap_minutes, min_hours_between_nudges, max_per_tick,
    # quiet_hours, online_recent_minutes, slots:{...}}. NULL → nudge_online's
    # built-in defaults (disabled until a rule + config enable it).
    nudge_config_json: Mapped[str | None] = mapped_column(Text)
    # W7 webhook-priority dispatch: per-account gate for real-time, event-driven
    # dispatch off inbound WS events. JSON {enabled: bool}. NULL/absent → OFF
    # (the safe default — no account reacts in real time until explicitly
    # enabled). A global env kill-switch (W7_WEBHOOK_DISPATCH_DISABLED) overrides
    # this. Kept separate from nudge_config_json to avoid the shallow-merge
    # collision in nudge_online._load_nudge_config.
    webhook_config_json: Mapped[str | None] = mapped_column(Text)
    # Per-account config for the `autoreply` automation (keep-warm re-engagement
    # of quiet, low-spend known fans). JSON: {enabled, silence_min_minutes,
    # silence_max_minutes, max_nudges, min_gap_minutes, max_lifetime_spend_cents,
    # recent_spend_days, max_recent_spend_cents, min_days_since_purchase,
    # min_days_since_first_chat, last_n_messages, quiet_hours_json}. Absent/NULL =
    # OFF. Separate column to avoid the nudge/webhook shallow-merge collision.
    autoreply_config_json: Mapped[str | None] = mapped_column(Text)
    # Per-automation opt-in for the "human texting style" package (short/casual
    # girl voice + 3-bubble splitting). JSON
    # {"welcome_chatter_for_info": bool, "autoreply": bool}. Absent/NULL or
    # a missing key → the per-automation default (see _common._STYLE_DEFAULT_ON).
    # Own column to avoid the nudge/webhook shallow-merge collision.
    style_config_json: Mapped[str | None] = mapped_column(Text)
    # RETIRED columns, still present on older databases but no longer mapped
    # (nothing reads or writes them; removed in the 2026-10 cleanup, and a DROP
    # COLUMN waits for the VPS row check): tip_reward_config_json,
    # ai_chatter_config_json, ppv_library_config_json, vault_ai_config_json,
    # make_right_config_json. Every one is nullable, so inserts without them work.
    # Include-only automation audience mode. Three COLUMNS, deliberately not keys
    # in a *_config_json blob: the mass senders never read those blobs, and every
    # blob writer is a strict allowlist whose one stale copy silently drops the
    # keys — a fail-open on an audience fence. NULL audience_mode ≡ 'off'
    # (default OFF; nullable so init_db's ADD-COLUMN catch-up lands it on prod
    # with no backfill). 'shadow' logs would-be skips and gates nothing;
    # 'enforce' gates. Shadow is mandatory before enforce (config API rule).
    audience_mode: Mapped[str | None] = mapped_column(String)
    # Local lists.id of the kind='automation_include' mirror row (NOT the OF
    # list id — that lives on the List row). Plain Integer, no FK: the additive
    # ALTER-ADD-COLUMN catch-up can't create constraints, and a fresh-box
    # create_all growing one the upgraded boxes lack would fork the schema.
    audience_list_id: Mapped[int | None] = mapped_column(Integer)
    # Auto-add newly subscribed fans to the include folder (roster-diff pull;
    # the mixed notifications feed is only a latency fast-path). NULL ≡ off.
    audience_auto_add: Mapped[bool | None] = mapped_column(Boolean)
    # Co-performer tagging (media_cotag) — the Brain's per-account overrides for
    # the global env knobs. Both nullable so init_db's ADD-COLUMN catch-up lands
    # them on prod with no backfill.
    #
    # NULL ≡ OFF: most creators are solo, and their videos really are just them.
    # True = the operator ticked "Always tag videos" on a COLLAB account: every
    # send attaching a vault VIDEO then carries the co-performer tag even when
    # the describe verdict reads it as solo — video describes are cut from
    # stills and miss the POV partner, which is how Blake1/Blake2 clips shipped
    # untagged. The describe-verdict decision itself is never weakened by this.
    cotag_tag_videos: Mapped[bool | None] = mapped_column(Boolean)
    # The handle to tag, stored without the '@' (media_cotag folds it the way OF
    # stores usernames). NULL = no co-creator tag, the default (ticket 85).
    cotag_username: Mapped[str | None] = mapped_column(String)
    # Split Inbox (ADR-0004): JSON {group_count: 1..9, assignments: {"<fanId>":
    # 1..group_count}}, owned by split_inbox_api. `assignments` holds only
    # explicit moves; every other Fan's group is computed in the app. NULL ≡ not
    # split. Nullable with no server default so init_db's ADD-COLUMN catch-up
    # lands it on an existing box with no backfill.
    split_inbox_json: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _ts_now()


class MassMessageFunnel(Base):
    """Funnel definitions — port of the JSON funnels (automation pack §15) into DB."""
    __tablename__ = "mass_message_funnels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    opening_message: Mapped[str] = mapped_column(Text, nullable=False)
    vault_folder: Mapped[str | None] = mapped_column(String)
    media_indices: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    opening_vault_folder: Mapped[str | None] = mapped_column(String)
    opening_media_indices: Mapped[str | None] = mapped_column(Text)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()


class FunnelAccountMedia(Base):
    """Per-(funnel, account) MEDIA binding for a shared funnel.

    A funnel's TEXT (opener + step copy/prompts/price) is GLOBAL — one
    definition shared across all of an owner's models (MassMessageFunnel). The
    MEDIA is NOT: an OnlyFans vault id is per-account, so an id picked on model A
    doesn't exist in model B's vault. Each model maps its OWN vault media to the
    shared funnel here, and reply_mass_funnel / send_mass_message resolve it by
    (funnel_id, account_id) at SEND time.

    `opening_media_ids` — JSON int array: the opener's vault media for this model.
    `steps_media_json`  — JSON object keyed by the step NUMBER (string), each
                          value `{"media_files": [int...], "previews": [int...]}`
                          — the vault media (and free-preview subset) this model
                          attaches to that funnel step. e.g.
                          `{"4": {"media_files": [123], "previews": [123]}}`.
                          Keyed by step number (not array index) so it survives a
                          step list that doesn't start at / isn't dense from 1.
    """
    __tablename__ = "funnel_account_media"

    funnel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mass_message_funnels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id"), primary_key=True,
    )
    opening_media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    steps_media_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()


class MassRun(Base):
    """One broadcast = one mass_runs row. funnel_state links per-fan state to this."""
    __tablename__ = "mass_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id"), nullable=False
    )
    funnel_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mass_message_funnels.id")
    )
    started_by_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id")
    )
    audience_filter: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # OF's broadcast queue id (result["id"]) — lets the Mass Messages tab join
    # mass_broadcast_cache.queue_id → this row to surface which automation +
    # funnel produced a cached broadcast. NULL for legacy pre-0032 runs.
    queue_id: Mapped[int | None] = mapped_column(BigInteger)
    # Which automation minted this broadcast (send_mass_message,
    # reply_mass_funnel, mass_nudge, online_blast). NULL = manual broadcast
    # from the UI or a legacy pre-0032 run.
    automation_kind: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = _ts_now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    # When the first mass was unsent/deleted → reply_mass_funnel STOPS enrolling
    # NEW repliers off this run (only replies at/before this cutoff enroll); the
    # walker keeps advancing fans already engaged until #30 halts them on a buy.
    # Stamped by close_funnel_discovery_for_queue on every unsend path.
    # Nullable/additive: init_db self-heals it via ALTER TABLE (no migration).
    discovery_closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # ── THE BLAST ITSELF, recorded at close (plans/blast-splice A.1) ────
    # A list-audience send (`userLists: ["fans","following"]`) writes NO per-fan
    # `messages` row — OF echoes no ids and the WS pump drops outbound frames — so
    # the line a fan is answering existed NOWHERE we could read it until his own
    # copy arrived on the inbox poll, p50 81 min after the send. The engine read a
    # two-word reply ("please") with nothing above it and called him out for not
    # answering her. These four columns are what the reply path reads instead.
    #
    # All four are NULLABLE and all four are load-bearing as a set: a run is
    # spliceable only with `body` AND `sent_at` AND `recipients_json`, so a legacy
    # row, a scheduled send that has not gone out, or an audience we could not
    # resolve is simply never spliced. init_db self-heals them via ALTER TABLE.
    body: Mapped[str | None] = mapped_column(Text)               # the text as sent
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)   # OF createdAt, else close time
    # Set when the queue is canceled (the 4h mass unsend, or "unsend from
    # everyone") — the run stops being spliceable the moment OF stops serving it.
    unsent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # JSON list[int]: who OF actually sent it to, RECORDED from OF's own rosters at
    # send time, never inferred from `audience_filter`. Measured on prod: 4 of the
    # 27 chat fans on one blast account are consistent non-recipients (expired
    # subscribers) with no local tell at all, so "everyone not excluded" would have
    # spliced 15% of repliers a blast they never received. NULL = we could not know
    # → never spliced (see audiences.resolve_recipients_blocking, which fails closed).
    recipients_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Mass Messages tab joins the cache to a run by (account_id, queue_id).
        Index(
            "ix_mass_runs_queue",
            "account_id",
            "queue_id",
            sqlite_where=text("queue_id IS NOT NULL"),
            postgresql_where=text("queue_id IS NOT NULL"),
        ),
        # …and "this account's runs in the last 48h" (built for the since-removed
        # ai_chatter's per-tick read; mass-run lookups still seek on it).
        Index("ix_mass_runs_account_sent", "account_id", "sent_at"),
    )


class FunnelState(Base):
    """Per-(mass_run, fan) state machine for reply_mass_funnel."""
    __tablename__ = "funnel_state"

    mass_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mass_runs.id", ondelete="CASCADE"), primary_key=True
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    check_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    # When this funnel last sent a paid_ppv step to the fan — the baseline for the
    # "offer taken" halt (#30). Nullable/additive: init_db self-heals it via
    # ALTER TABLE, so no migration (mirrors the rest of funnel_state).
    last_ppv_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Branching loop guard: how many times a `next` map has re-routed this fan.
    # A backward `next` can form a cycle; reply_mass_funnel halts the fan once
    # this passes ~20 hops (done + last_error='loop_guard') so a mis-authored
    # funnel can't spin forever. Nullable/additive (None == 0), self-heals via
    # ALTER TABLE like the columns above — a linear funnel never bumps it.
    hops: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = _ts_now()


class FunnelResponder(Base):
    """Durable per-(account, funnel) ledger of fans who ANSWERED a funnel's
    opener — the "already answered this campaign" dedup source (R1/R2).

    Written by reply_mass_funnel at DISCOVERY (a confirmed recipient of a run of
    this funnel who replied to the opener), so it is:
      • precise — only real opener-repliers, NOT anyone who happened to message
        us after the run started (avoids over-excluding other bot/human replies),
      • durable — survives funnel_state pruning + the run's messages being unsent,
      • per-funnel — keyed on funnel_id, so re-clicking Send skips prior answerers
        while a fresh audience is unaffected.
    resolve_mass_audience subtracts these ids from a funnel send's recipients.
    (A future "reset responders for this funnel" action would DELETE these rows to
    allow re-targeting the same funnel to the same fans.)"""
    __tablename__ = "funnel_responders"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    funnel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mass_message_funnels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The run that first observed the reply (provenance; not part of the key so a
    # later run of the same funnel doesn't double-insert the same answerer).
    mass_run_id: Mapped[int | None] = mapped_column(Integer)
    first_replied_at: Mapped[datetime] = _ts_now()


class CatalogItem(Base):
    """One sellable unit: a video, an image, or an image set (N media sold as one
    bundle). SINGLES (`script_id IS NULL`) are the whole catalog since the
    2026-08-19 script-ladder removal; rows with `script_id` set are legacy data
    — never offered again, kept because their open offers must still deliver
    and deleting them cascades into content_offers.

    `description_for_ai` is the contract: what the fan actually SEES, 1-2
    sentences, present tense. The LLM may only tease/claim what's written here —
    it is the sole source for pitches and for answering "what will we do?"."""
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    # LEGACY pair (retired 2026-08-19 with the script ladders): both default
    # NULL, nothing writes anything else, and `position` has no reader. Kept
    # for the legacy script rows; see CATALOG_IS_SINGLE below. No ForeignKey any
    # more: its target `catalog_scripts` is unmapped since the 2026-10 cleanup.
    # Older databases still carry the constraint (ON DELETE CASCADE) — see the
    # cleanup plan's pre-step 10(d) before ever dropping that table.
    script_id: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="video")
    label: Mapped[str | None] = mapped_column(String)      # e.g. "BOOB TEASE"
    description_for_ai: Mapped[str | None] = mapped_column(Text)
    media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Free teaser frames attached unlocked on a PPV send (OF `previews`).
    preview_media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    # v2 §4.2 — snapshot of the DERIVED price band per media, frozen at first quote
    # and recomputed only from the human 1:1 PAID subset. Exists so the deflationary
    # spiral (seller ingesting its own asks) can be watched/frozen; NULL until quoted.
    band_lo: Mapped[int | None] = mapped_column(Integer)
    band_hi: Mapped[int | None] = mapped_column(Integer)
    # Unlock terms. PPV is the only lane (2026-08-19): price_cents > 0 makes an
    # item sellable; is_free_teaser items are sent free to build momentum
    # (initiation pics, item 1). tip_unlock_cents is LEGACY data — nothing
    # offers on it anymore; it survives for the pre-ruling rows.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tip_unlock_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_free_teaser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_catalog_items_script", "account_id", "script_id", "position"),
    )


# The one canonical singles predicate (2026-08-19 ruling): every catalog READ —
# the seller's shelf, the editor, the settings transfer, the gap report — scopes
# with this exact clause so legacy script rows never resurface. Writers need
# nothing: `script_id`/`position` default NULL, so a plain CatalogItem(...) is a
# single by construction.
CATALOG_IS_SINGLE = CatalogItem.script_id.is_(None)


class ContentOffer(Base):
    """One concrete offer the since-removed ai_chatter made ('unlock this for $N /
    tip $M and i'll send it'); historical rows are kept, nothing writes new ones.
    The OPEN offer was the unlock watcher's anchor: inbound tips since
    `offered_at` accumulate into `tips_accum_cents` toward `tip_unlock_cents`;
    the ledger ingest flipping messages.is_paid on `offer_message_id` resolves a
    PPV. Doubles as the offer rate-limit source and the per-item conversion log.

    status: open → unlocked (paid, tip mode awaiting delivery) → delivered;
    PPV resolves straight to delivered (media was inside the locked message).
    expired = stall TTL; cancelled = superseded/killed by a human."""
    __tablename__ = "content_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    script_id: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String, nullable=False, default="tip")
    # Terms snapshot at offer time (catalog rows can be edited later).
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tip_unlock_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    offer_message_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    resolved_by: Mapped[str | None] = mapped_column(String)  # tip|ppv_ledger|ppv_fastpath|manual
    tips_accum_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_message_id: Mapped[int | None] = mapped_column(BigInteger)
    offered_at: Mapped[datetime] = _ts_now()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        # The watcher's hot path: the open offer for (account, fan).
        Index("ix_content_offers_open", "account_id", "fan_id", "status"),
        # Conversion stats per item ("which content actually sells").
        Index("ix_content_offers_item", "account_id", "item_id", "offered_at"),
    )


class AutomationRule(Base):
    """Declarative automation. Produces scheduled_jobs at runtime."""
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    trigger_json: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quiet_hours_json: Mapped[str | None] = mapped_column(Text)
    frequency_caps_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()


class ScheduledJob(Base):
    """Worker queue. The single async worker reads from this."""
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("automation_rules.id", ondelete="SET NULL")
    )
    created_by_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_jobs_due", "run_at", "status"),
        # ⚠️ `ix_jobs_due` leads on `run_at`, and EVERY hot query here bounds
        # `run_at <= now` — an open range from the oldest row. So the planner
        # walks that index from the beginning of time and filters status /
        # account_id / kind row by row. That was fine while this table held a
        # dozen rows a day; on 2026-08-12 the engines came on and it started
        # taking ~20k/day. Measured 2026-08-25 at 263,790 rows (of which 316
        # were actually pending/running): the executor spent 6.7s of every 30s
        # tick scanning, and `/admin/automation-rules` paid 833ms of it per
        # load. These three make the same questions O(matching rows).
        #
        # `ix_jobs_due` is deliberately KEPT: init_db()'s catch-up can create a
        # missing index but never drops a stale one, so removing it here would
        # leave it on disk everywhere anyway — and an A/B showed that taking an
        # index away can flip the planner onto a worse one.
        #
        # _has_pending_job (automation_rules_api), _claim_due_job and
        # _materialize_due_rules' pending guard — all (account, kind, status)
        # with a run_at bound.
        Index("ix_jobs_account_kind_status_run",
              "account_id", "kind", "status", "run_at"),
        # _due_job_pairs — status-first, no account, once per supervisor tick.
        Index("ix_jobs_status_run", "status", "run_at"),
        # The cadence anchor (`max(created_at) WHERE rule_id = ?`) had NO index
        # to use at all — a full table scan per rule per tick, 1.4s across 85
        # enabled rules.
        Index("ix_jobs_rule_created", "rule_id", "created_at"),
    )


class AutomationRun(Base):
    """Periodic-run audit log. So you can see 'gen_info_sweep last ran 8 min ago.'"""
    __tablename__ = "automation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = _ts_now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    stats_json: Mapped[str | None] = mapped_column(Text)
    error_text: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_runs_kind_started", "kind", "started_at"),
        # `_last_run` and the max_runs counter both filter (account_id, kind).
        # `ix_runs_kind_started` answers those by walking the KIND partition and
        # discarding rows belonging to other accounts — cheap while every model
        # runs every kind, and 297ms for the one shape that matters most: a kind
        # this account has NEVER run, where it walks the partition to find
        # nothing. That is exactly what a freshly-created rule asks.
        Index("ix_runs_account_kind_started", "account_id", "kind", "started_at"),
        # `/admin/stats/automation-runs` — ORDER BY started_at DESC over the
        # principal's accounts. clamp_account_filter turns the card's
        # unqualified call into `account_id IN (<every account you own>)`, so the
        # filtered shape IS the user-facing one; unindexed it scanned all 409k
        # rows into a temp b-tree (1.0s) on a card that polls every 60s.
        #
        # ⚠️ This one must ship WITH `ix_runs_account_kind_started`, never
        # instead of it. Measured on a snapshot: alone, the planner prefers it
        # for `_last_run` too and then walks the whole account partition
        # filtering kind — 0.2ms → 156ms, and max_runs_count 285ms → 1,443ms,
        # i.e. FIVE TIMES WORSE than adding no index at all.
        Index("ix_runs_account_started", "account_id", "started_at"),
    )


class FanLease(Base):
    """Per-fan send lease used by the automation executor (T-EXEC /
    MASTER_PLAN §5). Before any automation sends to a fan it must hold this
    lease, so two automations (A05/A06/A07/A11) can't message the same fan in
    overlapping ticks. PK (account_id, fan_id) = at most one live lease per
    fan; the holder writes a short leased_until TTL and releases (or lets it
    expire) after the send. One bot message per fan per cycle."""
    __tablename__ = "fan_lease"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    automation_kind: Mapped[str] = mapped_column(String, nullable=False)
    leased_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    acquired_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        # Cheap expiry sweeps: DELETE ... WHERE leased_until < now.
        Index("ix_fan_lease_expiry", "leased_until"),
    )


class NudgeState(Base):
    """Per-(account, fan) state for the nudge_online automation — "message a fan
    when they come online". Dedicated table (NOT fans.last_online_at, which the WS
    pump overwrites) so the detector's poll-and-diff and the re-engagement cap own
    their own timestamps.

      • last_seen_online_at — refreshed every tick a fan is in the online set;
        the detector's `newly_online` diff and the fire-job's recency re-validate
        both read this. Stale (> gap_minutes) ⇒ the fan re-qualifies.
      • last_nudged_at / nudge_count — drive the `min_hours_between_nudges`
        re-engagement cap (default 12h).
      • no_reply_streak — consecutive nudges with no inbound since; the no-reply
        backoff gate stops nagging a non-responder.
      • pending_job_id — the enqueued `nudge_online_fire` job awaiting its delay;
        dedup latch (skip re-scheduling while one is pending). CLEARED by the
        fire-job on send OR cancel.
      • last_variation_idx / last_slot — `repeat_mode` rotation: `new` advances
        the index through the slot's pool, `same` reuses it. NULL last_slot ⇒
        never nudged (seed the index from the fan id).

    Nudge is fully async: it NEVER sets fans.automation_paused_until (the shared
    cooldown), so the chat engines are never frozen by a nudge — it gates
    only on its own cap here.
    """
    __tablename__ = "nudge_state"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_seen_online_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_nudged_at: Mapped[datetime | None] = mapped_column(DateTime)
    nudge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_reply_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_job_id: Mapped[int | None] = mapped_column(Integer)
    last_variation_idx: Mapped[int | None] = mapped_column(Integer)
    last_slot: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        # Detector warm-up check + per-account state load.
        Index("ix_nudge_state_account", "account_id", "last_seen_online_at"),
    )


class FollowPingState(Base):
    """Per-(account, fan) follow-notification cooldown (`auto_follow.stamp_ping`):
    the last time a follow by auto_follow, send_welcome or lifecycle_messages
    fired a "started following you" push at this fan. Named for auto_follow's
    retired re-follow PING (Q9). Dedicated table (same pattern as NudgeState) so
    the cooldown survives restarts: without it every run would re-notify the
    same fans and the "notification" would read as harassment."""
    __tablename__ = "follow_ping_state"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_pinged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ping_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SubscriberSnapshot(Base):
    """The active-subscriber roster as of the last COMPLETE crawl by the Smart
    Messages lifecycle senders (automations/lifecycle_messages): one row per fan
    ever listed active, with OF's `subscribedOnData` dates. `seen_at` is the
    crawl that last listed him, so a row older than the newest crawl is a fan
    who is no longer active. `resubscribed_at` is set when a crawl lists a fan
    the previous crawl did not, with a newer `subscribe_at` — the Resubscribe
    trigger's event. `init_db`'s create_all makes it."""
    __tablename__ = "subscriber_snapshot"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subscribe_at: Mapped[datetime | None] = mapped_column(DateTime)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime)
    # OF's subscribedOnData.status: "active" = auto-renew on, anything else off.
    renew_on: Mapped[bool | None] = mapped_column(Boolean)
    seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resubscribed_at: Mapped[datetime | None] = mapped_column(DateTime)


class OfStatsDaily(Base):
    """One row per Creator per UTC day of OnlyFans Statistics figures, written
    by the daily snapshot job (of_stats_daily.py), so Creator reports can sum
    any window OF itself only answers live. A NULL is a figure we have no
    reading for, never a zero.

      visitors     Reach's profile visitors (`/users/me/profile/stats` chart)
      new_subs     the Subscriptions chart's New tab (`by=new`)
      renewals     its Renews tab (`by=renew`)
      active_fans  the roster (`subscriber_snapshot`) at the day's last crawl
      renew_on     of those, the fans with auto-renew on
      attempts / attempted_at
                   the OF fetches tried for the day and the last one: the
                   job's per-day cap, which survives a restart
    """
    __tablename__ = "of_stats_daily"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM-DD' UTC
    visitors: Mapped[int | None] = mapped_column(Integer)
    new_subs: Mapped[int | None] = mapped_column(Integer)
    renewals: Mapped[int | None] = mapped_column(Integer)
    active_fans: Mapped[int | None] = mapped_column(Integer)
    renew_on: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = _ts_now()
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime)


class OfEarningsDaily(Base):
    """One row per Creator per UTC day per OnlyFans earnings category, as
    OnlyFans' own Statistics › Statements charts it (`/earnings/chart`,
    of_stats_daily.py). The revenue and per-model reports read, per Creator,
    UTC day and category, the larger of these and the ledger's (stats.py
    `_of_top_ups`), which only holds what we ingested. Only complete days are
    stored, every category of a day in one read with OF's `total`; a day with
    no `total` row is one we have no reading for, never a zero.

      category     subscribes | tips | messages (OF's reply key `chat_messages`)
                   | post | stream, and `total`: OF's sum of them, the day's check
      net_cents    OF's chartAmount for the day (OF charts net, after its fee)
      gross_cents  that net times the category's gross/net over the same
                   reply (OF sends gross only as the period total)
      sales        OF's chartCount for the day
    """
    __tablename__ = "of_earnings_daily"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM-DD' UTC
    category: Mapped[str] = mapped_column(String, primary_key=True)
    net_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    sales: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    fetched_at: Mapped[datetime] = _ts_now()


class LifecycleMessageClaim(Base):
    """At most one message per (kind, fan, event) for the Smart Messages
    lifecycle senders — Nearing expiry, Expired, Resubscribe, Birthday. The
    event key names the occurrence (the subscription's expiry stamp, the new
    subscription's start, the birthday's year). INSERT … ON CONFLICT DO NOTHING
    before the send; deleted only when OnlyFans provably created nothing (a
    rate-limit refusal), as `purchase_followup_claims`.

    `message_idx` is which of the rule's messages (0-based, the rule's
    `messages` order) went out, written once OnlyFans answered the send with
    an id; NULL while it is in flight and for a send that never landed. The
    per-rule Buyers list reads only the landed ones. Added after the table
    existed: `init_db`'s additive catch-up adds the nullable column."""
    __tablename__ = "lifecycle_message_claims"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_key: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = _ts_now()
    message_idx: Mapped[int | None] = mapped_column(Integer)


class PriorityMassRun(Base):
    """One Priority mass message: one direct message per fan of a frozen
    audience (`priority_mass_recipients`), sent by `automations/priority_mass`.
    status: resolving (audience not frozen yet) → running → done, or cancelled /
    error. The message itself rides here: text, vault media ids, preview ids,
    price."""
    __tablename__ = "priority_mass_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    created_by_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String, nullable=False, default="resolving")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    previews_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # {user_lists, excluded_user_lists} as posted, resolved by the first leg.
    audience_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    resolved_count: Mapped[int | None] = mapped_column(Integer)   # before exclusions
    excluded_count: Mapped[int | None] = mapped_column(Integer)
    capped_count: Mapped[int | None] = mapped_column(Integer)     # past the 5,000 cap
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("ix_priority_mass_runs_account", "account_id", "created_at"),)


class PriorityMassRecipient(Base):
    """A fan of a Priority mass message's frozen audience. status: pending →
    claimed (committed BEFORE the wire) → sent / skipped / failed; a claim left
    by a crash becomes `unknown` and is never sent again."""
    __tablename__ = "priority_mass_recipients"

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("priority_mass_runs.id", ondelete="CASCADE"), primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(String)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (Index("ix_priority_mass_recipients_status", "run_id", "status"),)


class FollowLog(Base):
    """One row per follow notification we fired (`auto_follow.stamp_ping`) —
    the history the Auto-follow list's Today / Yesterday / 7 days / 30 days
    columns count. `follow_ping_state` keeps only the LAST time per fan, so it
    can answer "Total follows" (sum of ping_count) and "Last followed" but not a
    window. Append-only; `init_db`'s create_all makes it."""
    __tablename__ = "follow_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    fan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    followed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_follow_log_account_at", "account_id", "followed_at"),
    )


class AutoreplyState(Base):
    """Per-(account, fan) state for the `autoreply` automation — re-engage a quiet,
    low-spend known fan when WE spoke last and they've gone silent for a few
    minutes. Tracks the current silence "spell" so we never over-nudge:

      • spell_inbound_at — the fan's last_message_received_at at the time the
        current spell began. When the fan replies (their received_at advances
        past this), the spell resets and nudges_sent goes back to 0.
      • nudges_sent — autoreplies sent in the CURRENT spell; gated by the
        configurable max_nudges (default 1) so we stop until they reply.
      • last_nudge_at — enforces min_gap_minutes between nudges in a spell.

    Like nudge_online, autoreply NEVER sets fans.automation_paused_until (it gates
    on its own cap), so the chat engines are never frozen by it.
    """
    __tablename__ = "autoreply_state"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    spell_inbound_at: Mapped[datetime | None] = mapped_column(DateTime)
    nudges_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_nudge_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = _ts_now()


# ── §4.8 Grok call log ──────────────────────────────────────────────

class GrokCall(Base):
    """Every Grok API call. Logged BEFORE the request so failures don't lose audit."""
    __tablename__ = "grok_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str | None] = mapped_column(String)
    fan_id: Mapped[int | None] = mapped_column(BigInteger)
    model: Mapped[str] = mapped_column(String, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    temperature: Mapped[float | None] = mapped_column(Numeric(4, 2))
    # Never written. No ForeignKey: its target `prompts` is unmapped since the
    # 2026-10 cleanup (older databases still carry the SET NULL constraint).
    prompt_id: Mapped[int | None] = mapped_column(Integer)
    prompt_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_cents: Mapped[int | None] = mapped_column(Integer)
    # Provider that served this call ('grok' | 'deepseek' | …). Default 'grok'
    # backfills the pre-multiprovider rows. See 19_llm_providers.md §3.
    provider: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'grok'")
    )
    # DeepSeek bills prompt_cache_hit_tokens separately; NULL for providers
    # that don't report it.
    cache_hit_tokens: Mapped[int | None] = mapped_column(Integer)
    # 'pending' (written before the request) → 'done' | 'error'. llm_client
    # uses this once present; pre-migration it fell back to response_json IS NULL.
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'")
    )
    was_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_text: Mapped[str | None] = mapped_column(Text)
    called_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_grok_purpose_time", "purpose", "called_at"),
        Index(
            "ix_grok_fan",
            "account_id",
            "fan_id",
            "called_at",
            sqlite_where=text("fan_id IS NOT NULL"),
            postgresql_where=text("fan_id IS NOT NULL"),
        ),
        Index("ix_grok_prompt", "prompt_id", "called_at"),
    )


class TxHourly(Base):
    """`transactions` summed per UTC hour and per everything the stats reads
    group or filter by, kept exact by SQLite triggers on every write
    (tx_rollup.py). Stats read it instead of the wide ledger rows, and bucket
    its hours into the report zone's days with zoneinfo. NULL keys are stored
    as 0 / '' so the upsert's conflict target matches them."""
    __tablename__ = "tx_hourly"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    hour: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM-DD HH:00:00' UTC
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, primary_key=True)
    linked: Mapped[int] = mapped_column(Integer, primary_key=True)  # message_id IS NOT NULL
    employee_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # credit_employee_id, 0 = none
    rule: Mapped[str] = mapped_column(String, primary_key=True)
    automation_kind: Mapped[str] = mapped_column(String, primary_key=True)
    gross_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # net where OnlyFans reported it, else 80% of gross rounded down
    # ("Exclude the 20% OnlyFans fee", sales_attribution).
    net_or_80_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # OnlyFans' fee and VAT (`transactions.fee_cents` / `vat_cents`, NULL as 0),
    # added by 0083: the server default lets init_db's catch-up add them.
    fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    vat_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)


class TxDaily(Base):
    """`tx_hourly` by UTC day, kept by the same triggers: windows that need no
    hour buckets read their whole UTC days here, so a long window costs one
    row per day and credit instead of one per hour."""
    __tablename__ = "tx_daily"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM-DD' UTC
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, primary_key=True)
    linked: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule: Mapped[str] = mapped_column(String, primary_key=True)
    automation_kind: Mapped[str] = mapped_column(String, primary_key=True)
    gross_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    net_or_80_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    vat_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)


class GrokDailyCost(Base):
    """Daily LLM spend rollup. Source of truth for the soft cap enforcement.

    PK is `(day, account_id, provider)` so caps roll up per-account AND
    per-provider (grok vs deepseek vs …). account_id is nullable + part of the
    PK to allow a global rollup row alongside per-account rows; SQLite treats
    NULL as distinct in composite PKs. `provider` is NOT NULL (PK member) and
    defaults to 'grok' so pre-existing rows backfill cleanly — see migration
    0026_llm_provider, which mirrors the 0006 create-copy-swap PK rebuild."""
    __tablename__ = "grok_daily_cost"

    day: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM-DD' UTC
    account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(
        String, primary_key=True, nullable=False, server_default=text("'grok'")
    )
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_capped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = _ts_now()


class GrokUserDailyCost(Base):
    """The same daily soft-cap rollup as `grok_daily_cost`, for an LLM call that
    has NO account to bill: one row per (day, agency, provider).

    Today that is only the help bot asked by an agency with no OnlyFans account
    connected yet (`assistant_api`). `grok_daily_cost.account_id` is a foreign
    key to `accounts`, so there is no account row to key the cap on, and its
    NULL rollup row cannot cap anything — SQLite treats NULLs in a composite PK
    as distinct, so ON CONFLICT never fires on it. `llm_client._reserve` writes
    this table with the same one-statement reserve-and-check, under the same
    default cap. `user_id` is NOT NULL, and deleting the agency deletes its rows."""
    __tablename__ = "grok_user_daily_cost"

    day: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM-DD' UTC
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_capped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = _ts_now()


# ── §4.9 Realtime / event inbox ─────────────────────────────────────

class EventInbox(Base):
    """Every WS event lands here first. Idempotent via (source, provider_event_id)."""
    __tablename__ = "event_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = _ts_now()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    processed_status: Mapped[str | None] = mapped_column(String)
    processed_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Partial unique — only enforced when provider_event_id is present.
        Index(
            "uq_event_dedupe",
            "source",
            "provider_event_id",
            unique=True,
            sqlite_where=text("provider_event_id IS NOT NULL"),
            postgresql_where=text("provider_event_id IS NOT NULL"),
        ),
        Index(
            "ix_event_unprocessed",
            "processed_at",
            sqlite_where=text("processed_at IS NULL"),
            postgresql_where=text("processed_at IS NULL"),
        ),
    )


# ── §4.9b Application error log ─────────────────────────────────────

class AppError(Base):
    """Bug-hunter table: every unhandled exception (server or browser)
    lands here so we can review them without scraping log files.

    `source`  = "server" (FastAPI middleware) | "browser" (POSTed from
                the useErrorReporter hook).
    `kind`    = short tag — "unhandledrejection", "react-render",
                "fetch-error", "HTTPException", etc. Free-form; we just
                use it for filtering in /admin/errors.
    `message` = e.message or whatever short label the source provides.
    `stack`   = full stack trace if available.
    `url`     = window.location.href (browser) / request.url (server).
    `context` = JSON blob with anything else worth keeping (account_id,
                employee_id, user agent, query params, …).
    """
    __tablename__ = "app_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = _ts_now()
    source: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="error")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(String)
    employee_id: Mapped[int | None] = mapped_column(Integer)
    user_agent: Mapped[str | None] = mapped_column(Text)
    context_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_app_errors_occurred", "occurred_at"),
        Index("ix_app_errors_source_kind", "source", "kind"),
    )


# ── §4.11 Wall-media scan (incremental "posted on wall" tracking) ────

class WallMedia(Base):
    """Vault media IDs we've ever observed in this model's wall posts.
    Drives the blue "posted on wall" ring in the VaultPicker.

    Populated incrementally by /admin/vault/wall-media — each call walks
    OF's /posts feed forward (or backwards during backfill) and upserts
    rows here. Lookups read the union of every row for the account, so
    the ring is eventually-correct for prolific creators with >250
    lifetime posts (the old in-memory cap silently mis-flagged those)."""
    __tablename__ = "wall_media"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[int | None] = mapped_column(BigInteger)
    # Wall-post publishedAt — used during backfill to walk older history
    # via OF's before_publish_time cursor.
    post_published_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Highest price (in cents) this media was ever posted at on the wall.
    # 0 = free wall post (or price not yet observed). Drives the picker's
    # "WALL $X.XX" badge so a chatter can see the item is already public
    # PPV and at what price. Upserted via MAX() so a media seen in both a
    # free and a paid post keeps the paid signal (don't-undersell).
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_seen_at: Mapped[datetime] = _ts_now()

    # Redundant w/ the composite PK's leading column on SQLite, but kept
    # so `create_all()` and the Alembic migration produce identical
    # schemas across fresh-install / migrate paths.
    __table_args__ = (
        Index("ix_wall_media_account_id", "account_id"),
    )


class PerfEventRow(Base):
    """Client-side perfLog events, batch-ingested from the frontend so we
    can ask things like "across all chatters, what's the p95 from
    `vault.media requested` → `delivered`?" or "are popout windows on
    LAN-tunnel hosts slower than direct same-host opens?".

    Append-only. Pruned by `_perf_events_evict_once()` on a background
    timer (default 7 days; tune via env). No FK to accounts — the
    employee/account identity is best-effort `meta` payload, since the
    frontend may not know either at the moment a tab.open fires."""
    __tablename__ = "perf_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tab_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_tab_id: Mapped[str | None] = mapped_column(String)
    op_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    # Client epoch ms — store as BigInteger because raw ms is more useful
    # than a parsed datetime when reconstructing intra-second sequences
    # (multiple events can land in the same millisecond).
    client_ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[datetime] = _ts_now()
    # Soft identity hints — present when the client knew them at log time.
    employee_id: Mapped[int | None] = mapped_column(Integer)
    account_id: Mapped[str | None] = mapped_column(String)
    # JSON-encoded free-form meta. Capped at INGEST_META_MAX_BYTES
    # server-side so a runaway logger can't blow the row size.
    meta_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_perf_events_received_at", "received_at"),
        Index("ix_perf_events_tab_kind", "tab_id", "kind"),
        Index("ix_perf_events_op", "op_id"),
    )


class WallScanState(Base):
    """Per-account scan watermark for the wall-media walker. One row per
    account.

    Two phases:
      • Backfill (fully_backfilled=False): we haven't seen the bottom of
        the post feed yet. Subsequent calls walk backward from
        oldest_post_published_at.
      • Refresh (fully_backfilled=True): we've reached the bottom. Each
        call walks forward and stops as soon as it hits a post with
        publishedAt <= newest_post_published_at."""
    __tablename__ = "wall_scan_state"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    newest_post_published_at: Mapped[datetime | None] = mapped_column(DateTime)
    oldest_post_published_at: Mapped[datetime | None] = mapped_column(DateTime)
    fully_backfilled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    scanned_posts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TransactionScanHistory(Base):
    """Per-account watermark for the Phase F payouts/transactions ingest
    supervisor (service/transaction_ingest.py). Mirrors WallScanState's
    backfill→refresh state machine with the additional fields the ingest
    job needs (error/pause bookkeeping + insert/patch counters).

    Phases:
      • Backfill (fully_backfilled=False): walks 90d back from connect
        time toward `backfill_floor`; advances `oldest_seen_occurred_at`.
      • Refresh (fully_backfilled=True): re-fetches the trailing 7-day
        window every 10 min. `last_marker` is observability only —
        steady-state polling re-walks the window from scratch each tick.

    Auto-pause: after 3 consecutive failures the supervisor sets
    `paused_until = utcnow() + 1h` and `current_status='paused'`. Tick
    skips paused accounts until the cooldown elapses.
    """
    __tablename__ = "transaction_scan_history"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_marker: Mapped[int | None] = mapped_column(Integer)  # observability only
    oldest_seen_occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    newest_seen_occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    fully_backfilled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    backfill_floor: Mapped[datetime | None] = mapped_column(DateTime)
    current_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'idle'")
    )
    last_error: Mapped[str | None] = mapped_column(String)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    paused_until: Mapped[datetime | None] = mapped_column(DateTime)
    rows_inserted_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    rows_patched_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = _ts_now()


class MassBroadcastCache(Base):
    """Local cache of past mass-message broadcasts (OF queue rows).

    Source feed: GET /users/me/stats/messages/group. We pull this on a
    light schedule + on user-triggered "Refresh" and upsert here so the
    /settings → Mass messages tab opens instantly off SQLite instead of
    waiting for an OF roundtrip per account.

    Unlike per-chat unsend, mass-broadcast unsend has no edit window —
    `can_unsend` and `unsend_seconds` echo OF's flags so the UI knows
    whether the row is still actionable. When the user cancels, the
    DELETE on /messages/queue/{queue_id} succeeds and we flip
    `is_canceled=True` locally to avoid waiting for the next refresh.
    """
    __tablename__ = "mass_broadcast_cache"

    # NB: `text` would shadow the imported sqlalchemy.text() function
    # inside this class body, breaking every later `server_default=text(...)`
    # below — so we store OF's broadcast text under `body_text` and
    # serialize back to `text` at the boundary in mass_broadcast_cache.py.
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    queue_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    body_text: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    giphy_id: Mapped[str | None] = mapped_column(String)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_tip: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    media_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    media_json: Mapped[str | None] = mapped_column(Text)  # OF media[] passthrough
    previews_json: Mapped[str | None] = mapped_column(Text)  # int[] passthrough
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    viewed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_canceled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    can_unsend: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    unsend_seconds: Mapped[int | None] = mapped_column(Integer)
    template: Mapped[str | None] = mapped_column(String)
    fetched_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_mass_broadcast_cache_account_sent_at", "account_id", "sent_at"),
    )


# ── §X.X Multi-tenant auth (friends-only) ─────────────────────────
#
# See plan/simple_username_auth_2026_05_24/PLAN.md.
#
# Two tables. `users` holds (username, password) — plaintext per user
# decision; the relay is only exposed to a small friends group behind the
# share-token gate. `user_accounts` is the ownership join: which OF
# `accounts` rows a given user can see. `_resolve_account_id` consults
# this on every request to gate cross-user reads/writes.

class _LoginSecurity:
    """Session revoke and personal 2FA, the same five nullable columns on
    `users` and `chatters` (account_security.py; migration 0086_auth_sessions_2fa).

    `sessions_valid_after`: a session cookie issued before it is refused
    (auth.session_revoked), so "Log out other sessions", a password or 2FA reset and a
    deactivation sign every copy of the cookie out. `totp_secret` (base32) set
    means 2FA is on, since `totp_enabled_at`; `totp_recovery` is the JSON list of
    the unused backup codes' sha256; `totp_last_step` the last accepted TOTP
    time step, so a code is never accepted twice."""
    sessions_valid_after: Mapped[datetime | None] = mapped_column(DateTime)
    totp_secret: Mapped[str | None] = mapped_column(String)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    totp_recovery: Mapped[str | None] = mapped_column(Text)
    totp_last_step: Mapped[int | None] = mapped_column(Integer)


class User(_LoginSecurity, Base):
    """A friend with login access. No email, no OAuth — username + password
    only. Password stored plaintext per user decision (friends-only scale)."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid4 hex
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # stored lowercase
    password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = _ts_now()
    # Sliding 30-day inactivity expiry — bumped on every authenticated
    # request by the session middleware. Cookie is rejected once
    # (now - last_seen_at) > 30 days.
    last_seen_at: Mapped[datetime] = _ts_now()
    # Permanent master role. A master sees/acts on EVERY account (its
    # request-time account_ids snapshot becomes the full registry set — see
    # auth._auth_session_middleware) and sees every owner's employee roster
    # (the user_id scoping in employees.py is bypassed). Distinct from the
    # transient founder impersonation cookie. Flip via the ADMIN_PASSWORD
    # founder gate or a DB update; migration 0039_user_is_admin.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)


class UserAccount(Base):
    """Which OF accounts a user can see. Inserted on register (founder
    backfill) and on every successful login-capture (paste-curl / playwright
    bootstrap). Deleting a user CASCADE-clears these; deleting an OF account
    CASCADE-clears these too. The OF `accounts` row is the source of truth —
    these are pure ownership links."""
    __tablename__ = "user_accounts"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = _ts_now()


class UserLlmKey(Base):
    """One agency's LLM provider key. THE tenancy boundary for model spend.

    An owner (`users` row) is an agency; the OF accounts linked to it via
    `user_accounts` are its creators. Every LLM call that creator makes bills
    the key stored here, so two agencies can never spend on one credential —
    the invariant this table exists for. One row per (owner, provider); an
    agency that only uses DeepSeek simply has no deepinfra/grok row.

    `provider` holds a key of `llm_providers.PROVIDERS` ("deepseek" | "deepinfra" |
    "grok"). It is validated on the WRITE path against that registry rather
    than by a CHECK constraint, and the read path only ever queries a name that
    came out of the same registry — so a renamed provider can't silently make a
    stored key unreachable (which would fail over to the house key, i.e. to the
    deployment owner's bill).

    Plaintext, like `proxies.json` passwords and `secrets.json` — the same
    known limitation, tracked with them. `ON DELETE CASCADE` is what makes
    offboarding an agency actually destroy its credentials; `PRAGMA
    foreign_keys=ON` is wired at connect (db/engine.py) so it really fires.
    """
    __tablename__ = "user_llm_keys"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _ts_now()


class UserSetting(Base):
    """One agency's Settings blob for one Settings tab (ADR-0007).

    One row per (owner, tab); `tab` is one of the six Blob tabs that
    `settings_api.BLOB_TABS` allows. `config_json` is the whole JSON object the
    tab's Panel last saved — replaced whole on every PUT, each PUT validated by
    `settings_schema.parse_blob` and stamped `version: 1` (ADR-0012). Consumers
    read it through `settings_api.applied_blob`, never raw. `ON DELETE CASCADE`
    removes an agency's blobs with its `users` row.
    """
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tab: Mapped[str] = mapped_column(String, primary_key=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _ts_now()


class RuntimeSwitch(Base):
    """A runtime override of one relay switch (service/runtime_switches.py), set from
    Settings → System. One row per switch `name` (the env var's name); no row = env /
    default decides. `value_json` is a JSON bool or integer. `updated_by` is the
    master's username. Read once at boot and after each write into an in-process
    cache, never on the hot path. Migration 0098_runtime_switches."""
    __tablename__ = "runtime_switches"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = _ts_now()


# The Settings tabs kept as `SettingsVersion` rows instead of a `user_settings`
# blob (roadmap W6 6.4), and the `effective_from` of a blob moved from there.
VERSIONED_SETTINGS_TABS: tuple[str, ...] = ("sales", "time-tracking")
SETTINGS_EPOCH = datetime(1970, 1, 1)


class SettingsVersion(Base):
    """One saved version of a versioned Settings tab (VERSIONED_SETTINGS_TABS:
    `sales` and `time-tracking`), which live here and not in `user_settings`.

    Append-only: a save adds a row and never edits one. The version in effect
    at time `ts` is the row with the latest `effective_from <= ts` (naive UTC),
    the highest id among equal ones; before the first row the tab's defaults
    apply. A blob stored before versioning moved here at `effective_from` =
    SETTINGS_EPOCH (`db.engine.move_versioned_settings`), so history reads as
    it did. `config_json` is the
    whole blob as `user_settings` stored it. `ON DELETE CASCADE` with the user.
    """
    __tablename__ = "settings_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tab: Mapped[str] = mapped_column(String, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_settings_versions_user_tab", "user_id", "tab", "effective_from"),
    )


# ── Shifts and time tracking (docs/spec/phase-02-shifts-time-tracking.md) ──
#
# Every table is scoped to its Agency through `agency_user_id` (users.id).
# These models declare the same indexes as migration 0067_shifts, because
# deploys run `init_db()` (create_all + the additive catch-up), not
# `alembic upgrade` (see service/tests/test_automation_queue_indexes.py).

class Shift(Base):
    """A planned work interval in one Agency. `start_utc`/`end_utc` are the
    first occurrence (naive UTC, end > start, at most 24 h); `tz` is the IANA
    zone it was created in. `repeat_days` is a JSON list of ISO weekdays
    (1..7, in `tz`), NULL = no repeat; `repeat_until` is the last local date,
    inclusive, NULL = "Never". A cancel is soft: `status='cancelled'`.
    `cancelled_dates` is a JSON list of local dates (YYYY-MM-DD, in `tz`)
    whose occurrence is removed from the series, NULL = none: "This shift"
    deletes and edits (service/shifts_api.py)."""
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    start_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tz: Mapped[str] = mapped_column(Text, nullable=False)
    repeat_days: Mapped[str | None] = mapped_column(Text)
    repeat_until: Mapped[date | None] = mapped_column(Date)
    cancelled_dates: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="scheduled")
    created_by: Mapped[str] = mapped_column(Text, nullable=False)  # 'owner:<users.id>'
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("status IN ('scheduled','cancelled')", name="status"),
        Index("ix_shifts_agency_start", "agency_user_id", "start_utc"),
    )


class ShiftAssignment(Base):
    """One row per (Employee, Creator) pair of a Shift: a Shift with E
    Employees and C Creators stores E×C rows."""
    __tablename__ = "shift_assignments"

    shift_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shifts.id", ondelete="CASCADE"), primary_key=True
    )
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        Index("ix_shift_assignments_employee", "employee_id"),
        Index("ix_shift_assignments_account", "account_id"),
    )


class ClockEvent(Base):
    """One clock-in and its clock-out for one Employee, on one Creator or on
    none (`account_id` NULL: the agency-wide clock), optionally inside a
    Shift. `out_utc` NULL = open; the partial unique index keeps at most one
    open Clock event per Employee. `last_seen_utc` is the latest heartbeat
    while open, which the Auto clock-out's inactivity deadline counts from."""
    __tablename__ = "clock_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="SET NULL")
    )
    account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    shift_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("shifts.id", ondelete="SET NULL")
    )
    in_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    out_utc: Mapped[datetime | None] = mapped_column(DateTime)
    close_reason: Mapped[str | None] = mapped_column(Text)
    last_seen_utc: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('manual','auto','owner_edit')",
            name="close_reason",
        ),
        Index(
            "uq_clock_events_open_employee",
            "employee_id",
            unique=True,
            sqlite_where=text("out_utc IS NULL"),
            postgresql_where=text("out_utc IS NULL"),
        ),
        Index("ix_clock_events_agency_in", "agency_user_id", "in_utc"),
        Index("ix_clock_events_account_in", "account_id", "in_utc"),
    )


# ── Share for Share (docs/spec/phase-03-share-for-share.md) ──────────
#
# Every Creator foreign key cascades on delete, so deleting a Creator deletes
# its S4S rows; none of them holds fan data. These models declare the same
# constraints and indexes as migration 0068_s4s, because deploys run
# `init_db()` (create_all + the additive catch-up), not `alembic upgrade`.
#
# ASSUMPTION: the four models go in this module although it is far over the
# 1,000-line guide. Rung 3 (the Shift models above). Overturned by a split
# of db/models.py into per-concern modules.

class S4SProfile(Base):
    """One Creator's S4S Setting. No row = opted out with the defaults; a row
    is written only by the owner's first save."""
    __tablename__ = "s4s_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    opted_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    discovery_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        CheckConstraint("daily_limit BETWEEN 1 AND 3", name="daily_limit"),
    )


class S4SPost(Base):
    """One S4S post (a promo caption) of a Creator: at most 20 per Creator
    (the API's 409) and at most one Primary post (the partial unique index)."""
    __tablename__ = "s4s_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        CheckConstraint("length(caption) <= 5000", name="caption_length"),
        Index(
            "uq_s4s_posts_primary",
            "account_id",
            unique=True,
            sqlite_where=text("is_primary"),
            postgresql_where=text("is_primary"),
        ),
    )


class S4SRequest(Base):
    """An S4S request from one Creator to another for one `slot_at` (naive
    UTC). Both captions and both projections are snapshots taken at send."""
    __tablename__ = "s4s_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    to_account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    slot_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    from_caption: Mapped[str] = mapped_column(Text, nullable=False)
    to_caption: Mapped[str] = mapped_column(Text, nullable=False)
    from_projection_json: Mapped[str] = mapped_column(Text, nullable=False)
    to_projection_json: Mapped[str] = mapped_column(Text, nullable=False)
    # `[{id, media_type}]` of the `s4s_media` on each Primary post at send (ADR-0015);
    # NULL on requests sent before S4S media existed (read as no media).
    from_media_json: Mapped[str | None] = mapped_column(Text)
    to_media_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default=text("'pending'"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("from_account_id <> to_account_id", name="distinct_parties"),
        CheckConstraint(
            "status IN ('pending','accepted','declined','skipped','cancelled','expired')", name="status"
        ),
        Index(
            "uq_s4s_requests_open_pair",
            "from_account_id",
            "to_account_id",
            unique=True,
            sqlite_where=text("status IN ('pending','skipped')"),
            postgresql_where=text("status IN ('pending','skipped')"),
        ),
        Index("ix_s4s_requests_to_status", "to_account_id", "status"),
        Index("ix_s4s_requests_from_status", "from_account_id", "status"),
    )


class S4SSlot(Base):
    """One side of an accepted S4S request: `poster_account_id` posts `text`
    (the partner's caption plus an @mention) at `slot_at` (naive UTC)."""
    __tablename__ = "s4s_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("s4s_requests.id", ondelete="CASCADE"), nullable=False
    )
    poster_account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    partner_account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    slot_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # A plain-string server default: the `text` column above shadows sqlalchemy.text here.
    status: Mapped[str] = mapped_column(Text, nullable=False, default="scheduled", server_default="scheduled")
    reason: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(Integer)
    post_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("posts.id", ondelete="SET NULL"))
    of_post_id: Mapped[int | None] = mapped_column(BigInteger)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    remove_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("status IN ('scheduled','posting','posted','canceled','failed')", name="status"),
        Index("ix_s4s_schedule_poster_slot", "poster_account_id", "slot_at"),
    )


class S4SMedia(Base):
    """One S4S media item (ADR-0015): a reference to one of the Creator's own
    vault items (`vault_media_id`), checked with the Creator's own session when
    its owner attached it to an S4S post. No file is kept: the item is read
    from the vault when a partner posts it. `post_id` goes NULL when detached;
    the row goes once no open request or live slot names it."""
    __tablename__ = "s4s_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("s4s_posts.id", ondelete="SET NULL"))
    vault_media_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Unused since media became vault references; kept, with these defaults,
    # so the NOT NULL columns need no migration.
    file_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_s4s_media_account", "account_id"),
        Index("ix_s4s_media_post", "post_id"),
    )


class S4SBlock(Base):
    """An Agency's block on another Creator: hidden from the Agency's
    Discovery, and no request either way between it and the Agency's Creators.
    `projection_json` is the Creator's S4S projection when blocked, so the
    Blocked list never reads the other Agency live (ADR-0011)."""
    __tablename__ = "s4s_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    projection_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("agency_user_id", "account_id", name="uq_s4s_blocks_agency_account"),
    )


# ── Employee groups (docs/spec/phase-05-remaining-parity-gaps.md, item 4) ──
#
# The Organization Chart's tree: one Agency's groups, each under the Agency
# root (parent_id NULL) or under one of the same Agency's groups. Declares the
# same constraint and index as migration 0070_employee_groups, because deploys
# run `init_db()` (create_all + the additive catch-up), not `alembic upgrade`.

class EmployeeGroup(Base):
    """One Employee group of an Agency. Names are unique among siblings: the
    UNIQUE constraint holds under a group, and the router also checks the
    Agency root's children, which SQL's NULL `parent_id` never collides on."""
    __tablename__ = "employee_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("employee_groups.id"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("agency_user_id", "parent_id", "name"),
        Index("ix_employee_groups_agency", "agency_user_id"),
    )


# ── Growth > Sensitive words (service/sensitive_words_api.py) ──
#
# create_all makes this on boot (no alembic revision), like smart_lists.

class SensitiveWord(Base):
    """One word on an Agency's Sensitive words list. Infloww keeps one list per
    Agency, not per Creator; every composer warns on it. `word_key` is the
    word lowercased, so the list holds each word once whatever its case."""
    __tablename__ = "sensitive_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    word: Mapped[str] = mapped_column(String(32), nullable=False)
    word_key: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("agency_user_id", "word_key", name="uq_sensitive_words_agency_word"),
    )


# ── §X.Y Chatter login (one human, union of owners' accounts) ────────
#
# See Todo.txt STEP 8. A Chatter is a separate principal from a User.
# Owners (Users) link Chatters via chatter_users; the chatter then sees
# the SET UNION of every linked owner's UserAccount rows as their picker
# choices. Audit attribution per-action still goes through Employee, but
# the Employee row is auto-created on demand per (chatter, owner) pair so
# each owner sees a single "Tim" in their roster regardless of which
# other owners Tim is also linked to.

class Chatter(_LoginSecurity, Base):
    """A human chatter with login access. Distinct from User — Users are
    OF account OWNERS (founders, friends who run accounts); Chatters are
    the people who do the messaging work. One Chatter can be linked to
    many owners; one owner can link many Chatters. Picker selection
    persists per-tab in localStorage.

    Password column is plaintext per the same friends-scale risk decision
    as User.password — switch to a KDF before any wider exposure."""
    __tablename__ = "chatters"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid4 hex
    username: Mapped[str] = mapped_column(
        String, nullable=False, unique=True,
    )  # stored lowercase
    password: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String)
    color: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _ts_now()
    # Sliding 30-day inactivity expiry, same as User.last_seen_at — bumped
    # by the chatter session middleware on every authenticated request.
    last_seen_at: Mapped[datetime] = _ts_now()


class ChatterUser(Base):
    """Owner ↔ Chatter link. The chatter's available-accounts list is the
    UNION across all linked owners' UserAccount rows. CASCADE on both
    sides: deleting either party removes the link; existing Employee
    rows tied to the chatter on that owner stay (audit continuity) but
    become label-only when chatter_id is cleared via application code."""
    __tablename__ = "chatter_users"

    chatter_id: Mapped[str] = mapped_column(
        String, ForeignKey("chatters.id", ondelete="CASCADE"), primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    created_at: Mapped[datetime] = _ts_now()


class ChatterInvite(Base):
    """Owner-issued single-use signup token. The owner mints one + shares
    the URL with the new chatter; on first login that token grants access
    to /chatter/register AND auto-inserts the chatter_users row pointing
    back at the issuing owner. 24h TTL by default (see chatters.py)."""
    __tablename__ = "chatters_invites"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = _ts_now()
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    used_by_chatter_id: Mapped[str | None] = mapped_column(String)
    # The Employee setup to apply on acceptance — JSON of employees.EmployeeSetup
    # (role_id, account_ids, group_id, display_name). NULL = none (older invites).
    setup_json: Mapped[str | None] = mapped_column(Text)


# ── §X.Z Chatter access (owner-set per-chatter visibility limits) ────
#
# See library/CHATTER_ACCESS_PROMPTS.md. Two SUBTRACTIVE allowlists scoped
# per (chatter, owner). Both default to "empty = full access" so existing
# chatters are unaffected. Restriction applies ONLY when the acting
# principal is a chatter (no User cookie) — a dual-cookie owner is never
# limited (DA-1). To remove ALL access the owner UNLINKS the chatter; an
# empty restricted set is never persisted (DA-2).

class ChatterAccountAccess(Base):
    """Per (chatter, owner): which of THAT owner's models the chatter may
    see. If >=1 row exists for (chatter_id, user_id), that owner's
    contribution to the chatter's account union is restricted to the listed
    account_ids. No rows ⇒ no restriction (full access to that owner's
    models). Owner A's rows never affect owner B's contribution."""
    __tablename__ = "chatter_account_access"

    chatter_id: Mapped[str] = mapped_column(
        String, ForeignKey("chatters.id", ondelete="CASCADE"), primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True,
    )
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_chatter_account_access_chatter", "chatter_id"),
    )


class ChatterFolderAccess(Base):
    """Per (chatter, account): which OF vault folders the chatter may see.
    If >=1 row exists for (chatter_id, account_id), the chatter's vault
    browser for that account is restricted to the listed folder ids. No
    rows ⇒ no restriction.

    `folder_id` is BigInteger to match vault_items.folder_id (OF folder ids
    exceed int32); NOT a FK — vault folders aren't a local table.
    `folder_name` is denormalised at write time so the chatter's
    authoritative folder menu (/chatter/me/folder-access, DA-3) can render
    names without re-paginating OF's vault/lists."""
    __tablename__ = "chatter_folder_access"

    chatter_id: Mapped[str] = mapped_column(
        String, ForeignKey("chatters.id", ondelete="CASCADE"), primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True,
    )
    folder_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    folder_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_chatter_folder_access_chatter", "chatter_id"),
    )


class TranslationCache(Base):
    """Durable store behind POST /admin/translate — one row per (target, source text).

    The 🌐 toggle used to hold its translations in exactly two places, and BOTH
    were volatile: a module-level Map in the browser tab (gone on every reload or
    "↗ pop out") and an 8k-entry dict in the relay process (gone on every deploy).
    So the same Spanish thread was re-translated against Google's free gtx
    endpoint over and over — measured from the VPS, 40 uncached bubbles cost
    ~1.5s of wall clock before the first English word appears, and that bill was
    paid again on the next page load.

    Keyed by the TEXT, not by message id, which is the whole reason this pays for
    itself: over 30 days of prod chat, 193,471 rendered texts collapse to 86,949
    distinct ones — a 55% hit rate before a single fan repeats himself, because
    her side is largely scripted. A per-message column would translate "hola"
    thousands of times over.

    Server-side rather than localStorage for the same reason `vault_response_cache`
    is: it is shared. The first chatter to open a thread warms it for the whole
    team, in every tab, permanently — and it keeps the origin's contended ~5MB
    localStorage budget for the react-query snapshot.

    `text_hash` (md5 of target + NUL + text) is the primary key, so the source
    text is stored for pruning/debugging only and never looked up by value.
    """
    __tablename__ = "translation_cache"

    text_hash: Mapped[str] = mapped_column(String, primary_key=True)
    target: Mapped[str] = mapped_column(String, nullable=False)
    # ISO 639-1 as DETECTED by gtx ("es", "en", …) or "und". The UI tags bubbles
    # with it and renders same-language ones untouched, so it is part of the
    # cached answer, not metadata.
    src_lang: Mapped[str] = mapped_column(String, nullable=False, default="und")
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        # Backs the age-ordered prune (see translate_api._prune_locked). Without
        # it the cap sweep is a full scan of the largest table nobody reads.
        Index("ix_translation_cache_created", "created_at"),
    )


# ── Growth surfaces (gaps-lane: Infloww-gap features) ────────────────
# Five net-new tables backing the /growth page + the auto_follow automation.
# create_all makes these on boot (no alembic); every one is additive — no
# existing table is touched. See GAP_FEATURES_SPEC.md.

class SmartList(Base):
    """A saved dynamic fan segment. `rules_json` is a small DSL over per-fan
    facts (spend, dates, subscription state, tags — see smart_lists_api)
    resolved by smart_lists_api.resolve() into a fan-id set. Consumed as a
    named audience in the mass composer (include/exclude). An ACTIVE list is
    also mirrored into an OnlyFans user list it owns (`of_list_id`) by the
    `smart_list_sync` automation."""
    __tablename__ = "smart_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # JSON: {"match": "all"|"any", "rules": [{"field","op","value"}, ...]}
    rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()
    # ── OnlyFans sync (automations/smart_list_sync) ──
    # The OF list the sync CREATED for this row (never an adopted one), and the
    # name it last wrote there: a rename is reconciled whenever they differ.
    of_list_id: Mapped[int | None] = mapped_column(BigInteger)
    of_list_name: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), default=False)
    # syncing (the lock) | ok | pending (write budget hit) | error
    sync_state: Mapped[str | None] = mapped_column(String)
    sync_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)  # "Last updated"
    member_count: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_smart_lists_account", "account_id"),
        UniqueConstraint("account_id", "name", name="uq_smart_lists_account_name"),
    )


class TrialLinkMirror(Base):
    """Light local mirror of an OnlyFans free-trial link (source of truth is OF
    /trials). We store the create params + last-seen usage so the Growth table
    renders without a live round-trip and can label a link the operator named.
    `of_trial_id` links back to the OF entry; NULL until a create round-trips."""
    __tablename__ = "trial_link_mirrors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    of_trial_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String, nullable=False)
    subscribe_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    subscribe_counts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    url: Mapped[str | None] = mapped_column(Text)
    # Last-seen usage snapshot from OF (claimCounts) — refreshed on list().
    claim_counts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_trial_mirror_account", "account_id", "of_trial_id"),
    )


class TrackingLink(Base):
    """Internal UTM / tracking link. A `slug` (globally unique) is served at the
    public GET /t/{slug}, which records one TrackingClick row and 302s to
    `target_url`. Analytics = COUNT(clicks) over time (subs/$ attribution is a
    TODO — no reliable click→subscriber join exists yet; what it would take is
    written up in library/TRACKING_LINK_SPEND_PARKED.md)."""
    __tablename__ = "tracking_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Denormalized click counter (kept in sync on each capture) so the list
    # renders without an aggregate per row; TrackingClick holds the detail.
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("slug", name="uq_tracking_links_slug"),
        Index("ix_tracking_links_account", "account_id"),
    )


class TrackingClick(Base):
    """One row per hit on GET /t/{slug}. Kept thin — timestamp + a little
    provenance for the analytics readout (clicks over time / by referer)."""
    __tablename__ = "tracking_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracking_link_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracking_links.id", ondelete="CASCADE"), nullable=False
    )
    clicked_at: Mapped[datetime] = _ts_now()
    referer: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_tracking_clicks_link_time", "tracking_link_id", "clicked_at"),
    )


class PromoCampaign(Base):
    """Light local mirror of an OnlyFans subscription promo campaign (source of
    truth is OF /promotions). Stores the create params + last-seen performance
    so the Growth list renders and the operator can name/track a campaign.
    `of_promo_id` links back to the OF entry."""
    __tablename__ = "promo_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    of_promo_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # OF promos are a PERCENT discount off the sub (1–100). `discount_percent` is
    # the create-time value (OF does not echo it on list, so the mirror is the
    # only record). price_cents is kept for schema stability but is 0 for OF promos.
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscribe_counts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscribe_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    promo_type: Mapped[str] = mapped_column(String, nullable=False, default="all")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    # Last-seen performance snapshot from OF — claimsCount (people who claimed).
    subscriber_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # ── Auto-reactivate (promo_reactivate automation) ────────────────
    # Opt-in per campaign: when OF marks the promo finished (time or claims run
    # out), the automation re-creates it with the SAME discount/caps/message and
    # repoints of_promo_id at the new one. reactivate_count is the cycle counter
    # (also the cap check); last_reactivated_at drives the cooldown.
    auto_reactivate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reactivate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reactivated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_promo_campaigns_account", "account_id", "of_promo_id"),
    )


class LinkMeta(Base):
    """What we keep per OnlyFans link that OF itself does not: one row per
    (account, kind, OF id). kind is "trial" (a free trial link), "promo" (a
    profile promotion) or "campaign" (a tracking link).

    Operator input (Growth's Edit dialog, never written to OF), trial and
    campaign only: promo_cost_cents (Infloww's "Promo cost"; NULL = unset),
    source and tags_json (free text, a JSON list).

    Claimers cache state (link_metrics), trial and promo only: claim_count is
    OF's claim count at the last walk of the link's claimers (re-walked only
    when OF's count moves), walked_at that walk, checked_at the last refresh
    that compared the count. campaign_id is our promo_campaigns.id: a re-armed
    promotion's earlier OF promos keep it, so the campaign adds up across
    re-arms.

    The Edit dialog's List, trial and campaign: list_id / list_name are the
    OnlyFans fan list the link's claimers go into (OF's own "Add to list",
    which adds every current claimer in one idempotent call); list_added_count
    is OF's claim count at the last successful add (NULL: not added to this
    list yet), so the add re-runs only when the count grows past it."""
    __tablename__ = "link_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    of_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promo_cost_cents: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(String(100))
    tags_json: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[int | None] = mapped_column(Integer)
    claim_count: Mapped[int | None] = mapped_column(Integer)
    walked_at: Mapped[datetime | None] = mapped_column(DateTime)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    list_id: Mapped[str | None] = mapped_column(String(32))
    list_name: Mapped[str | None] = mapped_column(String(64))
    list_added_count: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("account_id", "kind", "of_id", name="uq_link_meta_link"),
    )


class LinkShare(Base):
    """Infloww's Share links (link_share_api): a public read-only report on
    some of one Creator's free trial links ("trial") or tracking links
    ("campaign"), at /share/<id>.<secret> for 7 days.

    secret is secrets.token_urlsafe, compared in constant time; the id is not
    secret. of_ids_json is the links picked (a JSON list of OF ids).
    rows_json is the report as the public sees it: per link only the name,
    the date created, the counts and, with include_earnings, the figures; no
    fan, no account id; null for a link not read yet. It is built from the
    owner's reads of the links after create and rebuilt on each later one
    (snapshot_at, null until the first), never from a public request. revoked_at set:
    the report answers 410, as it does past expires_at."""
    __tablename__ = "link_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    of_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    include_earnings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rows_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _ts_now()
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class PromoListSetting(Base):
    """Profile promotions' "Add fans to list" (Infloww's account-level switch
    and list on its Profile promotion page): while `enabled`, every
    promotion's claimers go into OnlyFans list `list_id` through OF's own
    add-to-list (link_metrics.sync_lists, kind "promo"). One row per account;
    no row = off."""
    __tablename__ = "promo_list_settings"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)
    list_id: Mapped[str | None] = mapped_column(String(32))
    list_name: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = _ts_now()


class LinkClaimer(Base):
    """A fan OnlyFans lists under a free trial link or a promotion (its
    claimers, /subscriptions/subscribers?filter[trial_id|promoId]).

    subscribe_at is OF's subscribedOnData.subscribeAt (the fan's current
    subscription start, the only date OF gives per fan) as first seen, and is
    never moved later: a fan who re-subscribes after the claim keeps the claim's
    time. NULL when OF sent no subscribedOnData (spend then reads "—").
    lifetime_*_cents are OF's *Summ (net, lifetime with the creator) as of the
    last walk; NULL without subscribedOnData."""
    __tablename__ = "link_claimers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    of_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String)
    subscribe_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lifetime_total_cents: Mapped[int | None] = mapped_column(Integer)
    lifetime_subs_cents: Mapped[int | None] = mapped_column(Integer)
    lifetime_posts_cents: Mapped[int | None] = mapped_column(Integer)
    lifetime_messages_cents: Mapped[int | None] = mapped_column(Integer)
    lifetime_streams_cents: Mapped[int | None] = mapped_column(Integer)
    lifetime_tips_cents: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("account_id", "kind", "of_id", "fan_id", name="uq_link_claimers_fan"),
    )


def is_paid_ratchet(is_paid: bool | None):
    """The upsert value for `messages.is_paid`: True, once set, never reverts.

    Use this in EVERY `on_conflict_do_update` that writes is_paid. Writing the
    scraped value directly is a silent revenue bug: `is_paid` is derived from
    the platform's `isOpened`, and on Fansly that answer is recovered from the
    purchases NOTIFICATION feed — one page, account-wide, which ages out. Once
    the row scrolls off, an honest re-scrape reports the message unpaid again,
    and an unconditional write erases a real sale.

    That is not cosmetic: revenue reads sum price_cents over is_paid rows, and
    ownership.py gates "does he already own this" on it — so
    a flipped-back row under-reports income AND re-offers bought content.

    One-way is also correct on OnlyFans: neither platform exposes an
    "un-purchase" signal on this path (purchase_notifications._flip_paid
    already treats the flip as one-way), and the transactions ledger — not a
    message scrape — is the money record. A free message still stores NULL.

    Lives here, beside the column, because two writers already need it
    (automation_executor's scrape upsert and event_transcoder's WS upsert) and
    a third would otherwise reintroduce the bug by simply forgetting.
    """
    return case((Message.is_paid.is_(True), True), else_=is_paid)
