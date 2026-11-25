from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
REPO_ROOT = SERVICE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from service.db.engine import DATABASE_URL
from service.db.models import Account, Proxy, Session as SessionRow


SESSIONS_DIR = SERVICE_ROOT / "sessions"
PROXIES_FILE = SERVICE_ROOT / "proxies.json"
ACTIVE_FILE = SESSIONS_DIR / "active.json"
ACCOUNTS_DIR = SESSIONS_DIR / "accounts"


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.replace("Z", "").rstrip(".")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y%m%dT%H%M%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def import_proxies(session: Session, dry_run: bool) -> int:
    if not PROXIES_FILE.exists():
        return 0
    data = json.loads(PROXIES_FILE.read_text())
    # Pool entries (`pool: true`) stay in proxies.json, never in SQL.
    keep = [p for p in data.get("proxies", []) if not p.get("pool")]
    custom = {p["label"] for p in keep}
    for row in session.scalars(select(Proxy).where(Proxy.label.like("infloww-%"))).all():
        if row.label not in custom:
            session.delete(row)
    count = 0
    for p in keep:
        existing = session.get(Proxy, p["label"])
        if existing:
            existing.scheme = p.get("scheme", existing.scheme)
            existing.host = p.get("host", existing.host)
            existing.port = p.get("port", existing.port)
            existing.username = p.get("username") or existing.username
            existing.password_encrypted = p.get("password") or existing.password_encrypted
            existing.notes = p.get("notes") or existing.notes
            existing.verified_ip = p.get("verified_ip") or existing.verified_ip
            existing.verified_at = _parse_ts(p.get("verified_at")) or existing.verified_at
            existing.assigned_account_id = p.get("assigned_account_id") or existing.assigned_account_id
        else:
            session.add(Proxy(
                label=p["label"],
                scheme=p.get("scheme", "http"),
                host=p["host"],
                port=int(p["port"]),
                username=p.get("username"),
                password_encrypted=p.get("password"),
                notes=p.get("notes"),
                verified_ip=p.get("verified_ip"),
                verified_at=_parse_ts(p.get("verified_at")),
                assigned_account_id=p.get("assigned_account_id"),
            ))
        count += 1
    if not dry_run:
        session.flush()
    return count


def _read_active_account_id() -> str | None:
    if not ACTIVE_FILE.exists():
        return None
    try:
        return json.loads(ACTIVE_FILE.read_text()).get("active_account_id")
    except Exception:
        return None


def import_accounts_and_sessions(session: Session, dry_run: bool) -> tuple[int, int]:
    if not ACCOUNTS_DIR.exists():
        return 0, 0

    active_id = _read_active_account_id()
    accounts_count = 0
    sessions_count = 0

    for adir in sorted(ACCOUNTS_DIR.iterdir()):
        if not adir.is_dir():
            continue
        account_id = adir.name
        meta_path = adir / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        latest_path = adir / "latest.json"
        latest_name = None
        if latest_path.exists():
            try:
                latest_name = json.loads(latest_path.read_text()).get("session")
            except Exception:
                pass

        existing_acc = session.get(Account, account_id)
        x_of_rev = static_param = user_agent = None
        if latest_name:
            sfile = adir / latest_name
            if sfile.exists():
                try:
                    sdata = json.loads(sfile.read_text())
                    h = sdata.get("headers", {})
                    rules = sdata.get("signing", {}).get("rules", {})
                    x_of_rev = h.get("x_of_rev")
                    user_agent = h.get("user_agent")
                    static_param = rules.get("static_param")
                except Exception:
                    pass

        bound_proxy = session.scalar(
            select(Proxy).where(Proxy.assigned_account_id == account_id)
        )
        proxy_label = bound_proxy.label if bound_proxy else None

        if existing_acc:
            existing_acc.nickname = meta.get("nickname") or existing_acc.nickname
            existing_acc.color = meta.get("color") or existing_acc.color
            existing_acc.proxy_label = proxy_label or existing_acc.proxy_label
            existing_acc.x_of_rev = x_of_rev or existing_acc.x_of_rev
            existing_acc.static_param = static_param or existing_acc.static_param
            existing_acc.user_agent = user_agent or existing_acc.user_agent
            existing_acc.is_active_default = (account_id == active_id) if active_id else existing_acc.is_active_default
            existing_acc.last_used_at = _parse_ts(meta.get("last_used_at")) or existing_acc.last_used_at
        else:
            session.add(Account(
                id=account_id,
                nickname=meta.get("nickname"),
                color=meta.get("color"),
                proxy_label=proxy_label,
                x_of_rev=x_of_rev,
                static_param=static_param,
                user_agent=user_agent,
                is_active_default=(account_id == active_id) if active_id else False,
                created_at=_parse_ts(meta.get("created_at")) or datetime.utcnow(),
                last_used_at=_parse_ts(meta.get("last_used_at")),
            ))
        accounts_count += 1

        for sfile in sorted(adir.glob("session_*.json")):
            try:
                sdata = json.loads(sfile.read_text())
            except Exception:
                continue
            captured_at = _parse_ts(sdata.get("captured_at"))
            if not captured_at:
                continue
            existing_sess = session.scalar(
                select(SessionRow).where(
                    SessionRow.account_id == account_id,
                    SessionRow.captured_at == captured_at,
                )
            )
            is_latest = (latest_name == sfile.name)
            cookies = sdata.get("cookies", [])
            rules = sdata.get("signing", {}).get("rules", {})
            if existing_sess:
                existing_sess.cookies_json = json.dumps(cookies)
                existing_sess.x_of_rev = sdata.get("headers", {}).get("x_of_rev", existing_sess.x_of_rev)
                existing_sess.signing_rules_json = json.dumps(rules)
                existing_sess.is_latest = is_latest
            else:
                session.add(SessionRow(
                    account_id=account_id,
                    captured_at=captured_at,
                    cookies_json=json.dumps(cookies),
                    x_of_rev=sdata.get("headers", {}).get("x_of_rev", ""),
                    signing_rules_json=json.dumps(rules),
                    is_latest=is_latest,
                ))
            sessions_count += 1

        if latest_name and not dry_run:
            session.flush()
            for s in session.scalars(
                select(SessionRow).where(SessionRow.account_id == account_id)
            ):
                pass

    if not dry_run:
        session.flush()
    return accounts_count, sessions_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy JSON state into SQLite.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change; don't commit.")
    args = parser.parse_args()

    sync_url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
    engine = create_engine(sync_url)
    with Session(engine) as s:
        proxies_n = import_proxies(s, args.dry_run)
        accounts_n, sessions_n = import_accounts_and_sessions(s, args.dry_run)
        if args.dry_run:
            s.rollback()
            print(f"[dry-run] would upsert: {proxies_n} proxies, {accounts_n} accounts, {sessions_n} sessions")
        else:
            s.commit()
            print(f"upserted: {proxies_n} proxies, {accounts_n} accounts, {sessions_n} sessions")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
