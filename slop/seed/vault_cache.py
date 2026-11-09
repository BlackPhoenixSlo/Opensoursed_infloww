"""Product-shaped vault response cache rows and chatter folder grants."""
from __future__ import annotations

import json
from . import ts

# app/hooks/useVaultMedia.ts: PAGE.
PICKER_PAGE = 24


def media_key(list_id: int | None = None, offset: int = 0) -> str:
    """service/vault_cache.vault_media_cache_key of a picker page (type all, newest first, no search)."""
    return f"media:type=all|list={list_id}|offset={offset}|limit={PICKER_PAGE}|sort=desc|field=recent|query="


# service/vault_cache.py: vault_lists_cache_key (fetchAllVaultLists' first page) and the picker's All page 1.
LISTS_KEY = "lists:view=main|limit=50|offset=0"
PICKER_KEY = media_key()


def cache_row(con, account_id: str, key: str, body: dict, at, *, replace: bool = False) -> None:
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    con.execute(f"{verb} INTO vault_response_cache(account_id, query_key, response_json, fetched_at) "
                "VALUES (?,?,?,?)", (account_id, key, json.dumps(body), ts(at)))


def grant_folder_access(con, chatter_id: str, account_id: str, folder_id: int,
                        folder_name: str, at) -> None:
    con.execute("INSERT INTO chatter_folder_access (chatter_id, account_id, folder_id, folder_name, created_at) "
                "VALUES (?,?,?,?,?)", (chatter_id, account_id, folder_id, folder_name, ts(at)))
