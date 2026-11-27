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
    Float,
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



def _now() -> datetime:
    return datetime.utcnow()


def _ts_now() -> Column:
    return mapped_column(
        DateTime, nullable=False, default=_now, server_default=text("CURRENT_TIMESTAMP")
    )



class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nickname: Mapped[str | None] = mapped_column(String)
    color: Mapped[str | None] = mapped_column(String)
    proxy_label: Mapped[str | None] = mapped_column(String)
    x_of_rev: Mapped[str | None] = mapped_column(String)
    static_param: Mapped[str | None] = mapped_column(String)
    user_agent: Mapped[str | None] = mapped_column(String)
    is_active_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _ts_now()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class Proxy(Base):
    __tablename__ = "proxies"

    label: Mapped[str] = mapped_column(String, primary_key=True)
    scheme: Mapped[str] = mapped_column(String, nullable=False)
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String)
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_ip: Mapped[str | None] = mapped_column(String)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    assigned_account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="SET NULL")
    )


class Session(Base):
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
        Index("ix_sessions_account_latest", "account_id", "is_latest"),
    )


class AccountHealth(Base):
    __tablename__ = "account_health"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Set => the automation executor skips every run for the account until a me() probe or re-capture clears it.
    session_dead_at: Mapped[datetime | None] = mapped_column(DateTime)
    session_dead_reason: Mapped[str | None] = mapped_column(String)
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Here, not meta.json: accounts.upsert_account rewrites that file and would drop the flag.
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _ts_now()
    user_id: Mapped[str | None] = mapped_column(String, index=True)
    chatter_id: Mapped[str | None] = mapped_column(String, index=True)
    group_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index(
            # Partial unique: the chatter auto-create path relies on ON CONFLICT DO NOTHING so simultaneous first mutations can't race-insert duplicate mirror rows.
            "uq_employees_chatter_owner",
            "chatter_id", "user_id",
            unique=True,
            sqlite_where=text("chatter_id IS NOT NULL"),
            postgresql_where=text("chatter_id IS NOT NULL"),
        ),
    )


class EmployeeAccountAccess(Base):
    __tablename__ = "employee_account_access"

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )


class Action(Base):
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
    via: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_actions_employee_at", "employee_id", "at"),
        Index("ix_actions_account_at", "account_id", "at"),
    )


class AgencyNotification(Base):
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
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("agency_user_id", "dedupe_key", name="uq_agency_notifications_dedupe"),
        Index("ix_agency_notifications_agency_created", "agency_user_id", "created_at"),
        Index("ix_agency_notifications_created", "created_at"),
    )



class Fan(Base):
    __tablename__ = "fans"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    of_username: Mapped[str | None] = mapped_column(String)
    of_display_name: Mapped[str | None] = mapped_column(String)
    avatar_url: Mapped[str | None] = mapped_column(Text)

    custom_nickname: Mapped[str | None] = mapped_column(String)
    generated_nickname: Mapped[str | None] = mapped_column(String)
    fan_chosen_nickname: Mapped[str | None] = mapped_column(String)

    real_name: Mapped[str | None] = mapped_column(String)
    is_name_real: Mapped[bool] = mapped_column(Boolean, default=True)
    his_age: Mapped[str | None] = mapped_column(String)
    birthday: Mapped[str | None] = mapped_column(String)
    salary: Mapped[str | None] = mapped_column(String)
    salary_frequency: Mapped[str | None] = mapped_column(String)
    last_pay_date: Mapped[str | None] = mapped_column(String)
    home_country: Mapped[str | None] = mapped_column(String)
    home_city: Mapped[str | None] = mapped_column(String)
    hobbies: Mapped[str | None] = mapped_column(Text)
    fetishes: Mapped[str | None] = mapped_column(Text)
    recent_events: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recent_events_timeline: Mapped[str | None] = mapped_column(Text)
    self_description: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    likes_boobs: Mapped[bool] = mapped_column(Boolean, default=False)
    likes_ass: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str | None] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String)
    language_source: Mapped[str | None] = mapped_column(String)

    occupation: Mapped[str | None] = mapped_column(Text)
    employer: Mapped[str | None] = mapped_column(Text)
    relationship_status: Mapped[str | None] = mapped_column(Text)
    partner_name: Mapped[str | None] = mapped_column(Text)
    has_kids: Mapped[bool | None] = mapped_column(Boolean)
    family_names: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    pets: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    mood_at_last_message: Mapped[str | None] = mapped_column(Text)
    sentiment_trend: Mapped[str | None] = mapped_column(Text)
    relationship_stage: Mapped[str | None] = mapped_column(Text)
    communication_style: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    automation_paused_until: Mapped[datetime | None] = mapped_column(DateTime)

    questions_asked: Mapped[str | None] = mapped_column(Text)

    persona_claims_json: Mapped[str | None] = mapped_column(Text)
    persona_age_claimed: Mapped[str | None] = mapped_column(Text)
    persona_location_claimed: Mapped[str | None] = mapped_column(Text)
    persona_job_claimed: Mapped[str | None] = mapped_column(Text)

    profile_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    grok_facts_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    notes: Mapped[str | None] = mapped_column(Text)
    applied_notes: Mapped[str | None] = mapped_column(Text)
    applied_notes_at: Mapped[datetime | None] = mapped_column(DateTime)
    # A column, not a ' Custom' suffix on custom_nickname: other writers rebuild the nickname and drop the marker.
    customs_owed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Settle stamp: customs_watch ignores tips at or before it, else the next sweep re-marks the same tip.
    customs_cleared_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Once-per-fan receipt for the closing PPV, stamped right after the send is on the wire; set means never send another.
    gather_close_at: Mapped[datetime | None] = mapped_column(DateTime)
    gather_close_sending_at: Mapped[datetime | None] = mapped_column(DateTime)

    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    custom_fields: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    lifetime_spend_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_likes: Mapped[int | None] = mapped_column(Integer)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    turn_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_message_received_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_message_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime)
    subscribed_at: Mapped[datetime | None] = mapped_column(DateTime)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    subscription_status: Mapped[str | None] = mapped_column(String)
    is_followed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Backfill progress marker, not the ping ledger (FollowPingState): examining a fan is not notifying him.
    follow_examined_at: Mapped[datetime | None] = mapped_column(DateTime)
    # OF chat-level mute; automations skip a muted creator we follow.
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)
    joined_date: Mapped[str | None] = mapped_column(String)

    # Dead columns of the removed deep_convo engine: dropping a SQLite column rewrites the table, which can corrupt the live WAL DB; drop only in its own deploy with a backup.
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



class Message(Base):
    __tablename__ = "messages"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    sender_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    media_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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

    mass_run_id: Mapped[int | None] = mapped_column(Integer)
    funnel_step: Mapped[int | None] = mapped_column(Integer)
    automation_kind: Mapped[str | None] = mapped_column(String)

    raw_json: Mapped[str | None] = mapped_column(Text)
    # Qwen3-VL description of an inbound photo the FAN sent. Nothing writes it any
    # more (the inbound describe was removed); rows described before that keep
    # theirs. NULL = never described. The chat engines read it back into history
    # as "[he sent: …]" so the AI can rate / react to it. Added 0052; nullable so
    # init_db's ADD-COLUMN catch-up materializes it on prod with no backfill.
    image_desc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ingested_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        ForeignKeyConstraint(["mass_run_id"], ["mass_runs.id"], ondelete="SET NULL"),
        Index("ix_messages_chat_seq", "account_id", "fan_id", "created_at", "message_id", "direction",
              "sent_by_employee_id", "mass_run_id", "automation_kind"),
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
        Index(
            "ix_messages_automation_kind",
            "account_id",
            "automation_kind",
            "created_at",
            sqlite_where=text("automation_kind IS NOT NULL"),
            postgresql_where=text("automation_kind IS NOT NULL"),
        ),
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


# Reads created_at without the DateTime parse: one '' cell otherwise raises out of .all() and takes the whole account's read down.
def created_at_text():
    return type_coerce(Message.created_at, String).label("created_at")


def parse_ts(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    # Naive UTC like the rest of the schema; an aware datetime breaks callers' arithmetic.
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class MessageMedia(Base):
    __tablename__ = "message_media"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str | None] = mapped_column(String)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    thumb_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ingested_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "fan_id", "message_id"],
            ["messages.account_id", "messages.fan_id", "messages.message_id"],
            ondelete="CASCADE",
        ),
        Index("ix_message_media_media", "account_id", "media_id"),
    )


class ScrapeHistory(Base):
    __tablename__ = "scrape_history"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_message_text: Mapped[str | None] = mapped_column(Text)
    last_scrape_at: Mapped[datetime] = _ts_now()
    history_deferred_at: Mapped[datetime | None] = mapped_column(DateTime)
    gap_after_id: Mapped[int | None] = mapped_column(BigInteger)
    gap_before_id: Mapped[int | None] = mapped_column(BigInteger)


# ── §4.4 Transactions (split for fast spend queries) ─────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    fan_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    raw_json: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = _ts_now()

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

    attributed_employee_id: Mapped[int | None] = mapped_column(Integer)

    credit_employee_id: Mapped[int | None] = mapped_column(Integer)
    credit_rule: Mapped[str | None] = mapped_column(String(16))
    credit_automation_kind: Mapped[str | None] = mapped_column(String)
    credit_sender_id: Mapped[int | None] = mapped_column(Integer)
    credit_converter_id: Mapped[int | None] = mapped_column(Integer)
    credit_converter_at: Mapped[datetime | None] = mapped_column(DateTime)

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
        Index(
            # Partial unique on the OF hash id: re-polls hit ON CONFLICT DO UPDATE (loading -> cleared); WS-pump rows (NULL) skip it.
            "uq_tx_provider_id",
            "account_id",
            "provider_transaction_id",
            unique=True,
            sqlite_where=text("provider_transaction_id IS NOT NULL"),
            postgresql_where=text("provider_transaction_id IS NOT NULL"),
        ),
        # Leads on status: the per-model pending query filters status != 'cleared' with no account_id.
        Index("ix_tx_status_occurred", "status", "occurred_at"),
        Index(
            # Cross-writer dedup: WS pump and PPV writer race on (account, fan, message_id); kind is deliberately not in the key.
            "uq_tx_msg",
            "account_id",
            "fan_id",
            "message_id",
            unique=True,
            sqlite_where=text("message_id IS NOT NULL"),
            postgresql_where=text("message_id IS NOT NULL"),
        ),
    )



class Chat(Base):
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
        Index("ix_chats_last_msg", "last_message_at"),
    )


class VaultItem(Base):
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

    search_text: Mapped[str | None] = mapped_column(Text)
    of_terms: Mapped[str | None] = mapped_column(Text)
    of_folder_ids: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String)
    content_hash_kind: Mapped[str | None] = mapped_column(String)
    updated_at_of: Mapped[str | None] = mapped_column(String)
    last_seen_run_id: Mapped[int | None] = mapped_column(BigInteger)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Signed: 0 first, 1,2,.. from the front, -1 last, -2,.. from the back; NULL = normal sort.
    manual_order: Mapped[int | None] = mapped_column(Integer)

    video_description: Mapped[str | None] = mapped_column(Text)
    explicitness_tier: Mapped[str | None] = mapped_column(String)
    story_suitable: Mapped[bool | None] = mapped_column(Boolean)
    story_score: Mapped[int | None] = mapped_column(Integer)
    tip_vault_flag: Mapped[bool | None] = mapped_column(Boolean)
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


    __table_args__ = (
        Index("ix_vault_account_created", "account_id", "created_at"),
        Index("ix_vault_account_send", "account_id", "send_count"),
        Index("ix_vault_account_seen", "account_id", "last_seen_run_id"),
        Index("ix_vault_account_describe", "account_id", "describe_status"),
    )


class VaultCacheRun(Base):
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
    __tablename__ = "vault_folder_items"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    folder_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    manual_order: Mapped[int | None] = mapped_column(Integer)
    added_at: Mapped[datetime] = _ts_now()

    __table_args__ = (Index("ix_vault_folder_items_folder", "account_id", "folder_id"),)


class VaultFolderPrice(Base):
    __tablename__ = "vault_folder_prices"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    folder_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = _ts_now()


class VaultAccountSetting(Base):
    __tablename__ = "vault_account_settings"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    folder_price_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    standard_folders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    solo_sequences: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = _ts_now()


class VaultOfQueryLog(Base):
    __tablename__ = "vault_of_query_log"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    query: Mapped[str] = mapped_column(String, primary_key=True)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_at: Mapped[datetime] = _ts_now()


class VaultResponseCache(Base):
    __tablename__ = "vault_response_cache"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    query_key: Mapped[str] = mapped_column(String, primary_key=True)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, server_default=text("CURRENT_TIMESTAMP"),
    )


# OF rejects creates on /messages/templates except reply_on_subscribe, so saved replies live only in our DB.
class SavedReply(Base):
    __tablename__ = "saved_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    media_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    tagged_users_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    previews_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    gif_id: Mapped[str | None] = mapped_column(String)
    gif_url: Mapped[str | None] = mapped_column(Text)
    script_id: Mapped[str | None] = mapped_column(String)
    script_step: Mapped[int | None] = mapped_column(Integer)
    tags_json: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    conditional: Mapped[str | None] = mapped_column(Text)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_saved_replies_account", "account_id", "updated_at"),
    )


class SavedReplySequence(Base):
    __tablename__ = "saved_reply_sequences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_saved_reply_sequences_account_name"),
    )


class VaultSend(Base):
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


class FanMediaSync(Base):
    __tablename__ = "fan_media_syncs"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# Claimed BEFORE the send, deleted only when OF provably created nothing; own table because fans.custom_fields is rewritten whole by other writers.
class PurchaseFollowupClaim(Base):
    __tablename__ = "purchase_followup_claims"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    purchased_message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    silent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                         server_default=text("0"))
    created_at: Mapped[datetime] = _ts_now()


class PurchaseNotice(Base):
    __tablename__ = "purchase_notices"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_purchase_notices_time", "account_id", "notified_at"),
    )


class Post(Base):
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
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
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



class FanProfile(Base):
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
    generated_by_grok_call_id: Mapped[int | None] = mapped_column(Integer)


class FollowupState(Base):
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
    sending_at: Mapped[datetime | None] = mapped_column(DateTime)
    sending_ctx: Mapped[str | None] = mapped_column(Text)
    unconfirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = _ts_now()


class WelcomeSent(Base):
    __tablename__ = "welcome_sent"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fan_username: Mapped[str | None] = mapped_column(String)
    sent_at: Mapped[datetime] = _ts_now()


class SkipList(Base):
    __tablename__ = "skip_list"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str | None] = mapped_column(String)
    added_at: Mapped[datetime] = _ts_now()


class Blacklist(Base):
    __tablename__ = "blacklist"

    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str | None] = mapped_column(String)
    added_at: Mapped[datetime] = _ts_now()


class AccountAiConfig(Base):
    __tablename__ = "account_ai_config"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    persona: Mapped[str | None] = mapped_column(Text)
    welcome_rules: Mapped[str | None] = mapped_column(Text)
    # IANA `timezone` below is DST-correct; this stays the fallback. Neither set => Human Rhythm disabled, not UTC (it would sleep a US creator through her peak).
    utc_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    model_notes: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String)
    voice: Mapped[str | None] = mapped_column(String)
    time_activities_json: Mapped[str | None] = mapped_column(Text)
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
    model: Mapped[str | None] = mapped_column(String)
    model_by_purpose: Mapped[str | None] = mapped_column(Text)
    reasoning_effort: Mapped[str | None] = mapped_column(String)
    nudge_config_json: Mapped[str | None] = mapped_column(Text)
    # Own column: nudge_config_json's shallow merge would collide.
    webhook_config_json: Mapped[str | None] = mapped_column(Text)
    full_ai_config_json: Mapped[str | None] = mapped_column(Text)
    autoreply_config_json: Mapped[str | None] = mapped_column(Text)
    style_config_json: Mapped[str | None] = mapped_column(Text)
    # Columns, not keys in a *_config_json blob: blob writers are strict allowlists that silently drop stale keys, a fail-open on the audience fence.
    audience_mode: Mapped[str | None] = mapped_column(String)
    audience_list_id: Mapped[int | None] = mapped_column(Integer)
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
    split_inbox_json: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _ts_now()


class MassMessageFunnel(Base):
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


# RUNNING before the POST; REFUSED = proxy refused it, OF never saw it; FAILED = surely not sent; INTERRUPTED = boot heal found RUNNING, OF may have taken it, never resent.
MASS_RUN_RUNNING = "running"
MASS_RUN_OK = "ok"
MASS_RUN_REFUSED = "refused"
MASS_RUN_FAILED = "failed"
MASS_RUN_INTERRUPTED = "interrupted"


class MassRun(Base):
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
    queue_id: Mapped[int | None] = mapped_column(BigInteger)
    automation_kind: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = _ts_now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, nullable=False, default=MASS_RUN_RUNNING)
    discovery_closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # List-audience sends may write no per-fan messages row; body/sent_at let readers see the mass.
    body: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    unsent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Retired with the audience crawl, never written; kept to avoid a migration.
    recipients_json: Mapped[str | None] = mapped_column(Text)
    crawl_outcome: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index(
            "ix_mass_runs_queue",
            "account_id",
            "queue_id",
            sqlite_where=text("queue_id IS NOT NULL"),
            postgresql_where=text("queue_id IS NOT NULL"),
        ),
        Index("ix_mass_runs_account_sent", "account_id", "sent_at"),
    )


class FunnelState(Base):
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
    last_ppv_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    hops: Mapped[int | None] = mapped_column(Integer)
    last_sent_step: Mapped[int | None] = mapped_column(Integer)
    confirmed_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sending_at: Mapped[datetime | None] = mapped_column(DateTime)
    sending_ctx: Mapped[str | None] = mapped_column(Text)
    unconfirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = _ts_now()


class FunnelResponder(Base):
    __tablename__ = "funnel_responders"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    funnel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mass_message_funnels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mass_run_id: Mapped[int | None] = mapped_column(Integer)
    first_replied_at: Mapped[datetime] = _ts_now()


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    script_id: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="video")
    label: Mapped[str | None] = mapped_column(String)
    description_for_ai: Mapped[str | None] = mapped_column(Text)
    media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    preview_media_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    band_lo: Mapped[int | None] = mapped_column(Integer)
    band_hi: Mapped[int | None] = mapped_column(Integer)
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


CATALOG_IS_SINGLE = CatalogItem.script_id.is_(None)


class ContentOffer(Base):
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
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tip_unlock_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    offer_message_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    resolved_by: Mapped[str | None] = mapped_column(String)
    tips_accum_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_message_id: Mapped[int | None] = mapped_column(BigInteger)
    offered_at: Mapped[datetime] = _ts_now()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_content_offers_open", "account_id", "fan_id", "status"),
        Index("ix_content_offers_item", "account_id", "item_id", "offered_at"),
    )


class AutomationRule(Base):
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
        # ix_jobs_due leads on run_at, so hot queries scan from the oldest row; the next three keep them O(matching). Kept: init_db never drops indexes and removing it can flip the planner.
        Index("ix_jobs_due", "run_at", "status"),
        Index("ix_jobs_account_kind_status_run",
              "account_id", "kind", "status", "run_at"),
        Index("ix_jobs_status_run", "status", "run_at"),
        Index("ix_jobs_rule_created", "rule_id", "created_at"),
    )


class AutomationRun(Base):
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
        Index("ix_runs_account_kind_started", "account_id", "kind", "started_at"),
        # Must ship WITH ix_runs_account_kind_started: alone the planner prefers it for _last_run and gets ~5x slower.
        Index("ix_runs_account_started", "account_id", "started_at"),
    )


class FanLease(Base):
    __tablename__ = "fan_lease"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    automation_kind: Mapped[str] = mapped_column(String, nullable=False)
    leased_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    acquired_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_fan_lease_expiry", "leased_until"),
    )


class NudgeState(Base):
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
        Index("ix_nudge_state_account", "account_id", "last_seen_online_at"),
    )


class FollowPingState(Base):
    __tablename__ = "follow_ping_state"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_pinged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ping_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SubscriberSnapshot(Base):
    __tablename__ = "subscriber_snapshot"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subscribe_at: Mapped[datetime | None] = mapped_column(DateTime)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime)
    renew_on: Mapped[bool | None] = mapped_column(Boolean)
    seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resubscribed_at: Mapped[datetime | None] = mapped_column(DateTime)


class OfStatsDaily(Base):
    __tablename__ = "of_stats_daily"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)
    visitors: Mapped[int | None] = mapped_column(Integer)
    new_subs: Mapped[int | None] = mapped_column(Integer)
    renewals: Mapped[int | None] = mapped_column(Integer)
    active_fans: Mapped[int | None] = mapped_column(Integer)
    renew_on: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = _ts_now()
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime)


class OfEarningsDaily(Base):
    __tablename__ = "of_earnings_daily"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    net_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    sales: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    fetched_at: Mapped[datetime] = _ts_now()


class LifecycleMessageClaim(Base):
    __tablename__ = "lifecycle_message_claims"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_key: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = _ts_now()
    message_idx: Mapped[int | None] = mapped_column(Integer)


class PriorityMassRun(Base):
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
    audience_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    resolved_count: Mapped[int | None] = mapped_column(Integer)
    excluded_count: Mapped[int | None] = mapped_column(Integer)
    capped_count: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("ix_priority_mass_runs_account", "account_id", "created_at"),)


class PriorityMassRecipient(Base):
    __tablename__ = "priority_mass_recipients"

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("priority_mass_runs.id", ondelete="CASCADE"), primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # claimed is committed BEFORE the wire; a crash leaves `unknown`, never sent again.
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(String)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (Index("ix_priority_mass_recipients_status", "run_id", "status"),)


class FollowLog(Base):
    __tablename__ = "follow_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    fan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    followed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_follow_log_account_at", "account_id", "followed_at"),
    )


class AutoreplyState(Base):
    __tablename__ = "autoreply_state"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    spell_inbound_at: Mapped[datetime | None] = mapped_column(DateTime)
    nudges_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_nudge_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = _ts_now()



class GrokCall(Base):
    __tablename__ = "grok_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str | None] = mapped_column(String)
    fan_id: Mapped[int | None] = mapped_column(BigInteger)
    model: Mapped[str] = mapped_column(String, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    temperature: Mapped[float | None] = mapped_column(Numeric(4, 2))
    prompt_id: Mapped[int | None] = mapped_column(Integer)
    prompt_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_cents: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'grok'")
    )
    cache_hit_tokens: Mapped[int | None] = mapped_column(Integer)
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
    __tablename__ = "tx_hourly"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    hour: Mapped[str] = mapped_column(String, primary_key=True)
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


class TxDaily(Base):
    __tablename__ = "tx_daily"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)
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
    __tablename__ = "grok_daily_cost"

    day: Mapped[str] = mapped_column(String, primary_key=True)
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
    __tablename__ = "grok_user_daily_cost"

    day: Mapped[str] = mapped_column(String, primary_key=True)
    # Separate from grok_daily_cost: its account_id NULL rollup row never conflicts (NULLs are distinct in a composite PK), so it can't cap.
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_capped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = _ts_now()



class EventInbox(Base):
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



class AppError(Base):
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



class WallMedia(Base):
    __tablename__ = "wall_media"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    media_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[int | None] = mapped_column(BigInteger)
    post_published_at: Mapped[datetime | None] = mapped_column(DateTime)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_seen_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_wall_media_account_id", "account_id"),
    )


class PerfEventRow(Base):
    __tablename__ = "perf_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tab_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_tab_id: Mapped[str | None] = mapped_column(String)
    op_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    client_ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[datetime] = _ts_now()
    employee_id: Mapped[int | None] = mapped_column(Integer)
    account_id: Mapped[str | None] = mapped_column(String)
    meta_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_perf_events_received_at", "received_at"),
        Index("ix_perf_events_tab_kind", "tab_id", "kind"),
        Index("ix_perf_events_op", "op_id"),
    )


class WallScanState(Base):
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
    __tablename__ = "transaction_scan_history"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    # OF ignores start/end, an ISO startDate answers empty and offset >= 600 answers empty (measured), so a full walk reads only the latest 600 rows.
    last_marker: Mapped[int | None] = mapped_column(Integer)
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
    last_full_at: Mapped[datetime | None] = mapped_column(DateTime)
    backfill_stalls: Mapped[int | None] = mapped_column(Integer)
    full_walk_failures: Mapped[int | None] = mapped_column(Integer)
    rows_inserted_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    rows_patched_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = _ts_now()


class MassBroadcastCache(Base):
    __tablename__ = "mass_broadcast_cache"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    queue_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Not `text`: it would shadow sqlalchemy.text() for the later server_default=text(...) in this class.
    body_text: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    giphy_id: Mapped[str | None] = mapped_column(String)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_tip: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    media_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    media_json: Mapped[str | None] = mapped_column(Text)
    previews_json: Mapped[str | None] = mapped_column(Text)
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



class _LoginSecurity:
    sessions_valid_after: Mapped[datetime | None] = mapped_column(DateTime)
    totp_secret: Mapped[str | None] = mapped_column(String)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    totp_recovery: Mapped[str | None] = mapped_column(Text)
    totp_last_step: Mapped[int | None] = mapped_column(Integer)


class User(_LoginSecurity, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # Plaintext by owner decision.
    password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = _ts_now()
    last_seen_at: Mapped[datetime] = _ts_now()
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)


class UserAccount(Base):
    __tablename__ = "user_accounts"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = _ts_now()


class OwnerToken(Base):
    __tablename__ = "owner_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    hint: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _ts_now()
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class UltraPlan(Base):
    __tablename__ = "ultra_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    step_states: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts_now()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class UserLlmKey(Base):
    __tablename__ = "user_llm_keys"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Validated against TENANT_KEY_PROVIDERS on write because unknown names never match a lookup.
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _ts_now()


class LeakTrackerTenant(Base):
    __tablename__ = "leak_tracker_tenant"

    agency_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LeakWatch(Base):
    __tablename__ = "leak_watch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agency_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    watch_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    platform: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default=text("''"))
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default=text("'[]'"))
    instagram: Mapped[str | None] = mapped_column(String)
    x: Mapped[str | None] = mapped_column(String)
    consent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consent_by: Mapped[str] = mapped_column(String, nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    synced_paused: Mapped[bool | None] = mapped_column(Boolean)
    offer_snoozed_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("agency_user_id", "account_id", name="uq_leak_watch_account"),
        UniqueConstraint("agency_user_id", "platform", "username", name="uq_leak_watch_handle"),
    )


class LeakWatchTombstone(Base):
    __tablename__ = "leak_watch_tombstone"

    watch_id: Mapped[str] = mapped_column(String, primary_key=True)
    agency_user_id: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts_now()


class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tab: Mapped[str] = mapped_column(String, primary_key=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _ts_now()


class RuntimeSwitch(Base):
    __tablename__ = "runtime_switches"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = _ts_now()


VERSIONED_SETTINGS_TABS: tuple[str, ...] = ("sales", "time-tracking")
SETTINGS_EPOCH = datetime(1970, 1, 1)


class SettingsVersion(Base):
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



class Shift(Base):
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
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("status IN ('scheduled','cancelled')", name="status"),
        Index("ix_shifts_agency_start", "agency_user_id", "start_utc"),
    )


class ShiftAssignment(Base):
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



class S4SProfile(Base):
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
    # Plain-string server default: the `text` column above shadows sqlalchemy.text here.
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
    __tablename__ = "s4s_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("s4s_posts.id", ondelete="SET NULL"))
    vault_media_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    file_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_s4s_media_account", "account_id"),
        Index("ix_s4s_media_post", "post_id"),
    )


class S4SBlock(Base):
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



class EmployeeGroup(Base):
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



class SensitiveWord(Base):
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



class Chatter(_LoginSecurity, Base):
    __tablename__ = "chatters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(
        String, nullable=False, unique=True,
    )
    password: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String)
    color: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _ts_now()
    last_seen_at: Mapped[datetime] = _ts_now()


class ChatterUser(Base):
    __tablename__ = "chatter_users"

    chatter_id: Mapped[str] = mapped_column(
        String, ForeignKey("chatters.id", ondelete="CASCADE"), primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    created_at: Mapped[datetime] = _ts_now()


class ChatterInvite(Base):
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
    setup_json: Mapped[str | None] = mapped_column(Text)



class ChatterAccountAccess(Base):
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
    __tablename__ = "chatter_folder_access"

    chatter_id: Mapped[str] = mapped_column(
        String, ForeignKey("chatters.id", ondelete="CASCADE"), primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True,
    )
    # BigInteger: OF folder ids exceed int32; not a FK, vault folders aren't a local table.
    folder_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    folder_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_chatter_folder_access_chatter", "chatter_id"),
    )


class TranslationCache(Base):
    __tablename__ = "translation_cache"

    text_hash: Mapped[str] = mapped_column(String, primary_key=True)
    target: Mapped[str] = mapped_column(String, nullable=False)
    src_lang: Mapped[str] = mapped_column(String, nullable=False, default="und")
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_translation_cache_created", "created_at"),
    )



class SmartList(Base):
    __tablename__ = "smart_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()
    of_list_id: Mapped[int | None] = mapped_column(BigInteger)
    of_list_name: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), default=False)
    sync_state: Mapped[str | None] = mapped_column(String)
    sync_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    member_count: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_smart_lists_account", "account_id"),
        UniqueConstraint("account_id", "name", name="uq_smart_lists_account_name"),
    )


class TrialLinkMirror(Base):
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
    claim_counts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_trial_mirror_account", "account_id", "of_trial_id"),
    )


class TrackingLink(Base):
    __tablename__ = "tracking_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bot_check: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), default=False)
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("slug", name="uq_tracking_links_slug"),
        Index("ix_tracking_links_account", "account_id"),
    )


class TrackingClick(Base):
    __tablename__ = "tracking_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracking_link_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracking_links.id", ondelete="CASCADE"), nullable=False
    )
    clicked_at: Mapped[datetime] = _ts_now()
    referer: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String(2))
    in_app: Mapped[str | None] = mapped_column(String)
    ref: Mapped[str | None] = mapped_column(String)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)

    __table_args__ = (
        Index("ix_tracking_clicks_stats", "tracking_link_id", "clicked_at", "verified", "country", "in_app", "ref"),
        Index("ix_tracking_clicks_unclassified", "id",
              sqlite_where=text("ref IS NULL"), postgresql_where=text("ref IS NULL")),
    )


class PromoCampaign(Base):
    __tablename__ = "promo_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    of_promo_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String, nullable=False)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscribe_counts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscribe_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    promo_type: Mapped[str] = mapped_column(String, nullable=False, default="all")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    subscriber_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_reactivate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reactivate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reactivated_at: Mapped[datetime | None] = mapped_column(DateTime)
    finish_days: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    recreates_left: Mapped[int | None] = mapped_column(Integer)
    keep_host_id: Mapped[str | None] = mapped_column(String)
    keep_warning: Mapped[str | None] = mapped_column(String)
    keep_warning_at: Mapped[datetime | None] = mapped_column(DateTime)
    keep_ticked_at: Mapped[datetime | None] = mapped_column(DateTime)
    preempt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                          server_default=text("1"))
    created_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_promo_campaigns_account", "account_id", "of_promo_id"),
        Index("uq_promo_keep_one", "account_id", unique=True,
              sqlite_where=text("auto_reactivate = 1"), postgresql_where=text("auto_reactivate")),
    )


class PromoCreateReservation(Base):
    __tablename__ = "promo_create_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("promo_campaigns.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    terms_json: Mapped[str] = mapped_column(Text, nullable=False)
    pre_ids_json: Mapped[str | None] = mapped_column(Text)
    replaced_of_promo_id: Mapped[int | None] = mapped_column(BigInteger)
    claims_seen: Mapped[int | None] = mapped_column(Integer)
    first_claims: Mapped[int | None] = mapped_column(Integer)
    host_id: Mapped[str | None] = mapped_column(String)
    of_promo_id: Mapped[int | None] = mapped_column(BigInteger)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_class: Mapped[str | None] = mapped_column(String)
    retry_after_s: Mapped[int | None] = mapped_column(Integer)
    not_before: Mapped[datetime | None] = mapped_column(DateTime)
    reconcile_reads: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                                 server_default=text("0"))
    created_at: Mapped[datetime] = _ts_now()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("uq_promo_create_open", "account_id", unique=True,
              sqlite_where=text("state IN ('pending','sending','unknown')"),
              postgresql_where=text("state IN ('pending','sending','unknown')")),
        Index("ix_promo_create_account_time", "account_id", "created_at"),
    )


class PromoKeepState(Base):
    __tablename__ = "promo_keep_state"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    kept_of_promo_id: Mapped[int | None] = mapped_column(BigInteger)
    first_claims: Mapped[int | None] = mapped_column(Integer)
    last_claims: Mapped[int | None] = mapped_column(Integer)
    seen_below: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                             server_default=text("0"))
    finished_at: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    recheck_at: Mapped[datetime | None] = mapped_column(DateTime)
    recheck_job_id: Mapped[int | None] = mapped_column(Integer)
    skew_s: Mapped[int | None] = mapped_column(Integer)
    wait_reason: Mapped[str | None] = mapped_column(String)


class LinkMeta(Base):
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
    __tablename__ = "promo_list_settings"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)
    list_id: Mapped[str | None] = mapped_column(String(32))
    list_name: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = _ts_now()


class LinkClaimer(Base):
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
        Index("ix_link_claimers_account_fan", "account_id", "fan_id"),
    )


# Use in EVERY is_paid upsert: writing the scraped value directly lets a later re-scrape erase a real sale.
def is_paid_ratchet(is_paid: bool | None):
    return case((Message.is_paid.is_(True), True), else_=is_paid)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    principal_kind: Mapped[str] = mapped_column(String, nullable=False)
    principal_id: Mapped[str] = mapped_column(String, nullable=False)
    issued_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    types: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    platforms: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        Index("ix_push_subscriptions_principal", "principal_kind", "principal_id"),
    )


class PushSent(Base):
    __tablename__ = "push_sent"

    sub_id: Mapped[str] = mapped_column(String, primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True)
    sent_at: Mapped[datetime] = _ts_now()

    __table_args__ = (Index("ix_push_sent_sent_at", "sent_at"),)


class AssistantTurn(Base):
    __tablename__ = "assistant_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = _ts_now()
    user_id: Mapped[str | None] = mapped_column(String)
    chatter_id: Mapped[str | None] = mapped_column(String)
    account_id: Mapped[str | None] = mapped_column(String)
    thread_id: Mapped[str | None] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    provider: Mapped[str | None] = mapped_column(String)
    cost_millicents: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_assistant_turns_user_ts", "user_id", "ts"),
        Index("ix_assistant_turns_chatter_ts", "chatter_id", "ts"),
        Index("ix_assistant_turns_ts", "ts"),
    )


class OfConsentAccept(Base):
    __tablename__ = "of_consent_accepts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(String)
    employee_id: Mapped[int | None] = mapped_column(Integer)
    at: Mapped[datetime] = _ts_now()

    __table_args__ = (Index("ix_of_consent_accepts_account_id", "account_id", "id"),)



class BioProfile(Base):
    __tablename__ = "bio_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str | None] = mapped_column(String, ForeignKey("accounts.id", ondelete="SET NULL"))
    username: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    bio: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    avatar: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    background_image: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    mode: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    v1_key: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)
    slot: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (UniqueConstraint("username", name="uq_bio_profiles_username"),)


class BioLink(Base):
    __tablename__ = "bio_links"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String, ForeignKey("bio_profiles.id", ondelete="CASCADE"), nullable=False
    )
    link_id: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    destination: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"), default="")
    default_tracking_code: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    mode: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    icon: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    background_image: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    v1_key: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    geo: Mapped[str | None] = mapped_column(Text)
    is_adult: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)
    tracking: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=False)
    sort_order: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"), default=0)
    bot_check: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"), default=True)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()

    __table_args__ = (
        UniqueConstraint("link_id", name="uq_bio_links_link_id"),
        Index("ix_bio_links_profile_order", "profile_id", "sort_order"),
    )


class BioCustomDomain(Base):
    __tablename__ = "bio_custom_domains"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String, ForeignKey("bio_profiles.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    token: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"), default="")
    checked: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_bio_custom_domains_profile_id"),
        Index("ix_bio_custom_domains_live", "domain", unique=True, sqlite_where=text("status = 'live'"),
              postgresql_where=text("status = 'live'")),
    )


class BioSpareDomain(Base):
    __tablename__ = "bio_spare_domains"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    domain: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("domain", name="uq_bio_spare_domains_domain"),)


class BioDaily(Base):
    __tablename__ = "bio_daily"

    day: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String, ForeignKey("bio_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    link_id: Mapped[str] = mapped_column(String, primary_key=True)
    country: Mapped[str] = mapped_column(String, primary_key=True)
    in_app: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, primary_key=True)
    views: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    __table_args__ = (Index("ix_bio_daily_profile_day", "profile_id", "day"),)



class AiDecision(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    fan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String, nullable=False)
    trigger_key: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_decisions.id"))
    anchor_message_id: Mapped[int | None] = mapped_column(BigInteger)
    anchor_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    arm: Mapped[str | None] = mapped_column(String)
    salt_ver: Mapped[int | None] = mapped_column(Integer)
    route: Mapped[str] = mapped_column(String, nullable=False)
    heat: Mapped[int] = mapped_column(Integer, nullable=False)
    route_row: Mapped[str] = mapped_column(String, nullable=False)
    question_version: Mapped[str] = mapped_column(String, nullable=False)
    router_model: Mapped[str | None] = mapped_column(String)
    writer_model: Mapped[str | None] = mapped_column(String)
    jev_json: Mapped[str | None] = mapped_column(Text)
    jev_ms: Mapped[int | None] = mapped_column(Integer)
    jev_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = _ts_now()
    updated_at: Mapped[datetime] = _ts_now()
    reply_json: Mapped[str | None] = mapped_column(Text)
    offer_price_cents: Mapped[int | None] = mapped_column(Integer)
    offer_list_cents: Mapped[int | None] = mapped_column(Integer)
    offer_media_json: Mapped[str | None] = mapped_column(Text)
    offer_item_ref: Mapped[str | None] = mapped_column(Text)
    offer_message_id: Mapped[int | None] = mapped_column(BigInteger)
    outcome: Mapped[str | None] = mapped_column(String)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime)
    join_src: Mapped[str | None] = mapped_column(String)
    offer_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        # Named unique INDEX, not a UniqueConstraint: SQLite keeps the name and init_db's index catch-up adds it by name.
        Index("uq_ai_decisions_turn", "account_id", "fan_id", "mode", "trigger_key", unique=True),
        Index("ix_ai_decisions_fan_time", "account_id", "fan_id", "created_at"),
        Index("ix_ai_decisions_acct_mode_time", "account_id", "mode", "created_at"),
        Index("uq_ai_decisions_offer_message", "account_id", "offer_message_id", unique=True,
              sqlite_where=text("offer_message_id IS NOT NULL"),
              postgresql_where=text("offer_message_id IS NOT NULL")),
    )


def _load_sibling_models() -> None:
    import importlib
    from pathlib import Path

    pkg = __name__.rpartition(".")[0]
    for path in sorted(Path(__file__).parent.glob("*_models.py")):
        importlib.import_module(f"{pkg}.{path.stem}" if pkg else path.stem)


_load_sibling_models()
