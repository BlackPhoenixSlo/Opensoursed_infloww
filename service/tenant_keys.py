# NO CACHE: an account transferred between owners would spend on the old owner's key until the entry aged out.
# Nothing ever copies the house key into an agency row: every seeder variant handed the deployment's credential to an account that should not have it.
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import Account, AccountHealth, User, UserAccount, UserLlmKey
import llm_providers
from llm_providers import PROVIDERS, TENANT_KEY_PROVIDERS, TYPESAFE
from secrets_store import MASK_CHAR, mask



def billable_owners(links: list[tuple[str, bool]]) -> list[str]:
    non_master = [ident for ident, is_master in links if not is_master]
    return non_master or [ident for ident, _ in links]


async def owners_of(account_id: str) -> list[str]:
    # A master's oversight link is dropped when a non-master link exists: billing the founder for agencies' traffic is the leak this module stops.
    if not account_id:
        return []
    async with get_session() as s:
        rows = (await s.execute(
            select(UserAccount.user_id, User.is_admin)
            .join(User, User.id == UserAccount.user_id)
            .where(UserAccount.account_id == account_id)
        )).all()
    return billable_owners(list(rows))


def payer_for(owners: list[str], keyed: dict[str, set[str]],
              provider: str) -> str | None:
    holders = [o for o in owners if provider in keyed.get(o, ())]
    return holders[0] if len(holders) == 1 else None


async def keyed_providers(user_ids) -> dict[str, set[str]]:
    ids = [u for u in (user_ids or []) if u]
    if not ids:
        return {}
    async with get_session() as s:
        rows = (await s.execute(
            select(UserLlmKey.user_id, UserLlmKey.provider)
            .where(UserLlmKey.user_id.in_(ids),
                   func.trim(UserLlmKey.api_key) != "")
        )).all()
    out: dict[str, set[str]] = {}
    for uid, prov in rows:
        out.setdefault(uid, set()).add(prov)
    return out


async def shared_accounts(account_ids) -> list[dict]:
    ids = [a for a in (account_ids or []) if a]
    if not ids:
        return []
    async with get_session() as s:
        rows = (await s.execute(
            select(UserAccount.account_id, User.id, User.username,
                   User.is_admin, Account.nickname)
            .join(User, User.id == UserAccount.user_id)
            .outerjoin(Account, Account.id == UserAccount.account_id)
            .where(UserAccount.account_id.in_(ids))
        )).all()
    keyed = await keyed_providers({uid for _, uid, _, _, _ in rows})
    name_of = {uid: username for _, uid, username, _, _ in rows}

    by_account: dict[str, dict] = {}
    for account_id, uid, username, is_admin, nickname in rows:
        entry = by_account.setdefault(
            account_id,
            {"account_id": account_id, "nickname": nickname or account_id,
             "links": []},
        )
        entry["links"].append((uid, bool(is_admin)))
    out = []
    for e in by_account.values():
        billable = billable_owners(e.pop("links"))
        if len(billable) < 2:
            continue
        pays: dict[str, str] = {}
        contested: list[str] = []
        for prov in sorted(PROVIDERS):
            payer = payer_for(billable, keyed, prov)
            if payer:
                pays[prov] = name_of[payer]
            elif sum(prov in keyed.get(o, ()) for o in billable) > 1:
                contested.append(prov)
        e["owners"] = sorted(name_of[o] for o in billable)
        e["pays"] = pays
        e["contested"] = contested
        out.append(e)
    out.sort(key=lambda e: e["nickname"].lower())
    return out


async def agency_exists(user_id: str) -> bool:
    if not user_id:
        return False
    async with get_session() as s:
        return await s.scalar(
            select(User.id).where(User.id == user_id)
        ) is not None


async def key_overview(registry: dict[str, bool],
                       required_providers: set[str]) -> list[dict]:
    # The registry, not the sessions table (frozen by a one-shot importer), says which accounts are live.
    async with get_session() as s:
        rows = (await s.execute(
            select(
                User.id, User.username, User.is_admin,
                UserAccount.account_id,
                AccountHealth.session_dead_at,
            )
            .join(UserAccount, UserAccount.user_id == User.id, isouter=True)
            .join(
                AccountHealth,
                AccountHealth.account_id == UserAccount.account_id,
                isouter=True,
            )
        )).all()

        keyed = (await s.execute(
            select(UserLlmKey.user_id, UserLlmKey.provider)
            .where(func.trim(UserLlmKey.api_key) != "")
        )).all()

    providers: dict[str, list[str]] = {}
    for uid, prov in keyed:
        providers.setdefault(uid, []).append(prov)

    out: dict[str, dict] = {}
    links: dict[tuple[str, str], bool] = {}
    owners_by_account: dict[str, list[tuple[str, bool]]] = {}
    for uid, username, is_admin, account_id, dead_at in rows:
        out.setdefault(uid, {
            "user_id": uid, "username": username, "is_admin": bool(is_admin),
            "accounts": 0, "live_accounts": 0, "blocked_accounts": 0,
            "providers_set": sorted(providers.get(uid, [])),
            "missing_providers": sorted(
                required_providers - set(providers.get(uid, []))),
        })
        if not account_id or account_id not in registry:
            continue
        links[(uid, account_id)] = registry[account_id] and dead_at is None
        owners = owners_by_account.setdefault(account_id, [])
        if (uid, bool(is_admin)) not in owners:
            owners.append((uid, bool(is_admin)))

    keyed = {u: set(p) for u, p in providers.items()}
    for (uid, account_id), is_live in links.items():
        billable = billable_owners(owners_by_account.get(account_id, []))
        if not billable:
            continue
        payer = billable[0]
        if len(billable) > 1:
            # A required provider two keyed owners both hold is a dispute the relay refuses: reported against both, counted for neither.
            contested = any(
                sum(prov in keyed.get(o, ()) for o in billable) > 1
                for prov in required_providers)
            if contested:
                if uid in billable and is_live:
                    out[uid]["blocked_accounts"] += 1
                continue
            payer = next(
                (payer_for(billable, keyed, prov)
                 for prov in sorted(required_providers)
                 if payer_for(billable, keyed, prov)),
                billable[0])
        if payer != uid:
            continue
        out[uid]["accounts"] += 1
        if is_live:
            out[uid]["live_accounts"] += 1

    return sorted(
        out.values(),
        key=lambda e: (-e["live_accounts"], -e["blocked_accounts"],
                       -e["accounts"], e["username"].lower()),
    )


async def get_key(user_id: str, provider: str) -> str:
    if not user_id or not provider:
        return ""
    async with get_session() as s:
        val = await s.scalar(
            select(UserLlmKey.api_key).where(
                UserLlmKey.user_id == user_id,
                UserLlmKey.provider == provider,
            )
        )
    return (val or "").strip()


async def set_keys(user_id: str, values: dict[str, str | None]) -> None:
    known = TENANT_KEY_PROVIDERS
    cleaned: dict[str, str] = {}
    for prov, raw in values.items():
        if prov not in known:
            raise ValueError(f"unknown provider {prov!r}; known: {known}")
        if raw is not None and not isinstance(raw, str):
            raise ValueError(f"{prov}: expected a string key, got {type(raw).__name__}")
        val = (raw or "").strip()
        if MASK_CHAR in val:
            raise ValueError(
                f"{prov}: that looks like the masked placeholder, not a key — "
                "leave the field blank to keep the stored value"
            )
        cleaned[prov] = val
    if not cleaned:
        return
    now = datetime.utcnow()
    async with get_session() as s:
        for prov, val in cleaned.items():
            stmt = sqlite_insert(UserLlmKey).values(
                user_id=user_id, provider=prov, api_key=val, updated_at=now,
            )
            await s.execute(stmt.on_conflict_do_update(
                index_elements=[UserLlmKey.user_id, UserLlmKey.provider],
                set_={"api_key": val, "updated_at": now},
            ))


async def status(user_id: str) -> dict[str, dict]:
    async with get_session() as s:
        rows = (await s.execute(
            select(UserLlmKey.provider, UserLlmKey.api_key)
            .where(UserLlmKey.user_id == user_id)
        )).all()
    have = {prov: (val or "").strip() for prov, val in rows}
    return {
        prov: {"set": bool(have.get(prov)), "hint": mask(have.get(prov, ""))}
        for prov in TENANT_KEY_PROVIDERS
    }


async def typesafe_key_for(account_id: str | None) -> str:
    owners = await owners_of(account_id or "")
    payer = payer_for(owners, await keyed_providers(owners), TYPESAFE) if owners else None
    if payer:
        key = await get_key(payer, TYPESAFE)
        if key:
            return key
    return llm_providers.typesafe_key()


async def typesafe_key_of(user_id: str) -> str:
    return await get_key(user_id, TYPESAFE) or llm_providers.typesafe_key()
