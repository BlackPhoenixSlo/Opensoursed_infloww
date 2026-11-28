#!/usr/bin/env python3
import _harness

import re
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

import platforms
from of_client import OFClient
from side_effect_gate import refusal

TABLE = Path(__file__).resolve().parents[2] / "app" / "lib" / "platform.ts"

CAP_METHODS: dict[str, tuple[str, ...]] = {
    "pin_message": ("pin_message", "unpin_message", "get_pinned_messages"),
    "mark_unread": ("mark_chat_unread",),
    "restrict": ("restrict_user", "unrestrict_user"),
    "block": ("block_user", "unblock_user"),
    "chat_search": ("search_chat",),
    "chat_media": ("chat_media",),
    "vault_remove": ("hide_vault_media",),
    "mass_message": ("send_mass_message", "schedule_mass_message", "mass_message_history"),
    "mass_history": ("mass_message_history", "engagement_messages"),
    "discount": ("set_subscription_discount",),
    "native_templates": ("message_templates",),
    "notifications_read": ("notifications_read",),
    "subscriber_chart": ("subscribers_chart",),
    "fan_activity": ("transactions",),
    "native_welcome": ("my_settings",),
}
APP_ONLY = frozenset({"rich_text", "filter_tips", "filter_priority", "filter_folders"})
assert not set(CAP_METHODS) & APP_ONLY

_CAPS = re.compile(r"export const CAPABILITIES = \[(.*?)\] as const", re.S)
_PLATFORMS = re.compile(r"export const PLATFORMS = \[(.*?)\] as const", re.S)
_KEY = re.compile(r'\{\s*key:\s*"(\w+)",\s*label:\s*"[^"]*",')
_LACKS = re.compile(r"\blacks:\s*\[(.*?)\]", re.S)
_TEXT_FIELDS = ("relink", "loginDefault", "extensionFormId", "sessionPrompt")
_TEXT = re.compile(rf'\b({"|".join(_TEXT_FIELDS)}):\s*"([^"]*)"')
_BINDS = re.compile(r"\bbindsProxy:\s*(true|false)\b")
_PROFILE_HOST = re.compile(r'\bprofileHost:\s*(?:null\b|"([^"]*)")')
_LOGO_PATH = re.compile(r'\{\s*d:\s*"M[^"]+",\s*fill:\s*"#[0-9A-Fa-f]{3,8}"\s*\}')
_STR = re.compile(r'"(\w+)"')


class Row(NamedTuple):
    key: str
    lacks: frozenset[str]
    fields: dict


def _objects(body: str) -> list[str]:
    out, depth, start, quoted = [], 0, 0, False
    for i, ch in enumerate(body):
        if ch == '"' and body[i - 1] != "\\":
            quoted = not quoted
        elif quoted:
            continue
        elif ch == "{":
            depth, start = depth + 1, (i if depth == 0 else start)
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append(body[start:i + 1])
    return out


def _row(obj: str) -> Row | None:
    key, lacks = _KEY.match(obj), _LACKS.search(obj)
    if not key or not lacks:
        return None
    fields: dict = dict(_TEXT.findall(obj))
    if binds := _BINDS.search(obj):
        fields["bindsProxy"] = binds[1] == "true"
    if host := _PROFILE_HOST.search(obj):
        fields["profileHost"] = host[1]
    fields["logo"] = len(_LOGO_PATH.findall(obj))
    return Row(key[1], frozenset(_STR.findall(lacks[1])), fields)


def parse(text: str) -> tuple[list[str], list[Row]]:
    text = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*[\s\S]*?\*/', lambda m: m[1] or " ", text)
    caps = _CAPS.search(text)
    table = _PLATFORMS.search(text)
    rows = [r for r in map(_row, _objects(table.group(1))) if r] if table else []
    return _STR.findall(caps.group(1)) if caps else [], rows


def _field_failures(row: Row, registered) -> list[str]:
    out = [] if row.fields.get("logo") else [f"{row.key}: no logo path"]
    out += [f"{row.key}: missing {f}" for f in (*_TEXT_FIELDS, "bindsProxy", "profileHost") if f not in row.fields]
    if (login := row.fields.get("loginDefault")) is not None and login not in ("browser", "extension"):
        out.append(f"{row.key}: loginDefault {login!r} is not browser or extension")
    binds = row.fields.get("bindsProxy")
    if registered is not None and binds is not None and binds != registered.bind_login_proxy:
        out.append(f"{row.key}: bindsProxy {binds} but registry bind_login_proxy {registered.bind_login_proxy}")
    return out


def failures(caps: list[str], rows: list[Row], registry) -> list[str]:
    out: list[str] = []
    if not caps:
        out.append("no Capabilities parsed from the Platform table")
    if not rows:
        out.append("no Platform rows parsed from the Platform table")
    if unlisted := set(caps) - set(CAP_METHODS) - APP_ONLY:
        out.append(f"Capabilities neither mapped nor app-only: {sorted(unlisted)}")
    if stale := (set(CAP_METHODS) | APP_ONLY) - set(caps):
        out.append(f"mapped or app-only but not a Capability: {sorted(stale)}")
    for cap, names in CAP_METHODS.items():
        out += [f"{cap}: {n} is not an OFClient method" for n in names if not hasattr(OFClient, n)]
    keys = [r.key for r in rows]
    if sorted(keys) != sorted(p.key for p in registry):
        out.append(f"table keys {sorted(keys)} != registry keys {sorted(p.key for p in registry)}")
    by_key = {p.key: p for p in registry}
    for r in rows:
        out += _field_failures(r, by_key.get(r.key))
    lacks = {r.key: r.lacks for r in rows}
    if lacks.get("onlyfans"):
        out.append(f"onlyfans lacks {sorted(lacks['onlyfans'])}")
    out += [f"{p.key}: no Backend module" for p in registry if p.key != "onlyfans" and p.backend is None]
    checked = [p for p in registry if p.backend is not None and p.key in lacks]
    if not checked:
        out.append("no registered Backend module has a table row")
    for p in checked:
        shim = p.backend.Shim
        for cap, names in CAP_METHODS.items():
            verdict = {n: refusal(shim, n) is not None for n in names}
            if (cap in lacks[p.key]) != any(verdict.values()):
                verdicts = ", ".join(f"{n}={'refused' if r else 'built'}" for n, r in verdict.items())
                out.append(f"{p.key}: {cap} {'in' if cap in lacks[p.key] else 'not in'} lacks but Shim has {verdicts}")
    return out


def case_table_matches_every_shim():
    caps, rows = parse(TABLE.read_text())
    print(f"{len(caps)} Capabilities, rows {[(r.key, len(r.lacks)) for r in rows]}")
    problems = failures(caps, rows, platforms.ALL)
    assert not problems, f"{len(problems)} drift failures:\n  " + "\n  ".join(problems)


class _AllRefused:
    pass


class _PinBuilt:
    def pin_message(self):
        return {}


_OF = SimpleNamespace(key="onlyfans", backend=None, bind_login_proxy=True)
_ALL_CAPS = [*CAP_METHODS, *APP_ONLY]


def _registry(shim) -> tuple:
    return (_OF, SimpleNamespace(key="fake", backend=SimpleNamespace(Shim=shim), bind_login_proxy=False))


def _fields(binds_proxy: bool, **over) -> dict:
    fields = {"logo": 1, "relink": "fake", "loginDefault": "extension", "extensionFormId": "fake-form",
              "sessionPrompt": "none", "bindsProxy": binds_proxy, "profileHost": "fake.example"}
    return {k: v for k, v in {**fields, **over}.items() if v is not None}


def _rows(lacks, **fake_over) -> list[Row]:
    return [Row("onlyfans", frozenset(), _fields(True)), Row("fake", frozenset(lacks), _fields(False, **fake_over))]


def case_fake_shim_refusing_all_matches_full_lacks():
    assert failures(_ALL_CAPS, _rows(_ALL_CAPS), _registry(_AllRefused)) == []


def case_unparseable_table_fails():
    caps, rows = parse("export const PLATFORMS = [{ key: 'x' }] as const")
    got = failures(caps, rows, _registry(_AllRefused))
    assert "no Capabilities parsed from the Platform table" in got, got
    assert "no Platform rows parsed from the Platform table" in got, got


def case_dropped_lack_fails():
    got = failures(_ALL_CAPS, _rows(set(_ALL_CAPS) - {"block"}), _registry(_AllRefused))
    assert got == ["fake: block not in lacks but Shim has block_user=refused, unblock_user=refused"], got


def case_commented_lacks_do_not_count():
    original = TABLE.read_text()
    entry = '"pin_message",'
    offset = original.index(entry, original.index("export const PLATFORMS"))
    for replacement in (f"/* {entry} */", f"// {entry}\n"):
        caps, rows = parse(original[:offset] + replacement + original[offset + len(entry):])
        got = failures(caps, rows, platforms.ALL)
        assert any(problem.startswith("fansly: pin_message not in lacks") for problem in got), got


def case_partial_capability_must_be_lacked():
    got = failures(_ALL_CAPS, _rows(set(_ALL_CAPS) - {"pin_message"}), _registry(_PinBuilt))
    assert len(got) == 1 and got[0].startswith("fake: pin_message not in lacks"), got


def case_partial_lacked_capability_passes():
    assert failures(_ALL_CAPS, _rows(_ALL_CAPS), _registry(_PinBuilt)) == []


def case_unlisted_capability_fails():
    got = failures([*_ALL_CAPS, "new_cap"], _rows(_ALL_CAPS), _registry(_AllRefused))
    assert got == ["Capabilities neither mapped nor app-only: ['new_cap']"], got


def case_table_keys_differ_from_registry_fails():
    got = failures(_ALL_CAPS, [*_rows(_ALL_CAPS), Row("other", frozenset(), _fields(True))], _registry(_AllRefused))
    assert got == ["table keys ['fake', 'onlyfans', 'other'] != registry keys ['fake', 'onlyfans']"], got


def case_registry_key_missing_from_table_fails():
    registry = (*_registry(_AllRefused), SimpleNamespace(key="other", backend=SimpleNamespace(Shim=_AllRefused)))
    got = failures(_ALL_CAPS, _rows(_ALL_CAPS), registry)
    assert got == ["table keys ['fake', 'onlyfans'] != registry keys ['fake', 'onlyfans', 'other']"], got


def case_non_onlyfans_platform_without_backend_fails():
    registry = (*_registry(_AllRefused), SimpleNamespace(key="other", backend=None, bind_login_proxy=True))
    got = failures(_ALL_CAPS, [*_rows(_ALL_CAPS), Row("other", frozenset(), _fields(True))], registry)
    assert got == ["other: no Backend module"], got


def case_onlyfans_lacking_fails():
    rows = [Row("onlyfans", frozenset({"block"}), _fields(True)), *_rows(_ALL_CAPS)[1:]]
    assert failures(_ALL_CAPS, rows, _registry(_AllRefused)) == ["onlyfans lacks ['block']"]


def case_table_rows_carry_setup_fields():
    _, rows = parse(TABLE.read_text())
    got = {r.key: {k: v for k, v in r.fields.items() if k != "logo"} for r in rows}
    assert got == {
        "onlyfans": {"relink": "browserbase", "loginDefault": "browser", "extensionFormId": "extension-login-form",
                     "sessionPrompt": "none", "bindsProxy": True, "profileHost": None},
        "fansly": {"relink": "fansly", "loginDefault": "extension", "extensionFormId": "fansly-session-form",
                   "sessionPrompt": "Please login Fansly", "bindsProxy": False, "profileHost": "fansly.com"},
    }, got
    assert all(r.fields["logo"] >= 1 for r in rows), [(r.key, r.fields.get("logo")) for r in rows]


def case_binds_proxy_mismatch_fails():
    got = failures(_ALL_CAPS, _rows(_ALL_CAPS, bindsProxy=True), _registry(_AllRefused))
    assert got == ["fake: bindsProxy True but registry bind_login_proxy False"], got


def case_missing_row_field_fails():
    got = failures(_ALL_CAPS, _rows(_ALL_CAPS, sessionPrompt=None, profileHost=None, logo=0), _registry(_AllRefused))
    assert got == ["fake: no logo path", "fake: missing sessionPrompt", "fake: missing profileHost"], got


def case_bad_login_default_fails():
    got = failures(_ALL_CAPS, _rows(_ALL_CAPS, loginDefault="phone"), _registry(_AllRefused))
    assert got == ["fake: loginDefault 'phone' is not browser or extension"], got


def case_empty_parse_fails():
    for text in ("", "export const PLATFORMS = [] as const"):
        _, rows = parse(text)
        got = failures(_ALL_CAPS, rows, _registry(_AllRefused))
        assert "no Platform rows parsed from the Platform table" in got, (text, got)


if __name__ == "__main__":
    _harness.run()
