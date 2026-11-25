#!/usr/bin/env python3
import _harness

import re
from pathlib import Path
from types import SimpleNamespace

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
    "discount": ("set_subscription_discount",),
    "native_templates": ("message_templates",),
}
APP_ONLY = frozenset({"rich_text", "filter_tips", "filter_priority", "filter_folders"})
assert not set(CAP_METHODS) & APP_ONLY

_CAPS = re.compile(r"export const CAPABILITIES = \[(.*?)\] as const", re.S)
_PLATFORMS = re.compile(r"export const PLATFORMS = \[(.*?)\] as const", re.S)
_ROW = re.compile(r'\{\s*key:\s*"(\w+)",\s*label:\s*"[^"]*",\s*lacks:\s*\[(.*?)\]\s*\}', re.S)
_STR = re.compile(r'"(\w+)"')


def parse(text: str) -> tuple[list[str], list[tuple[str, frozenset[str]]]]:
    text = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*[\s\S]*?\*/', lambda m: m[1] or " ", text)
    caps = _CAPS.search(text)
    table = _PLATFORMS.search(text)
    return (
        _STR.findall(caps.group(1)) if caps else [],
        [(k, frozenset(_STR.findall(lacks))) for k, lacks in _ROW.findall(table.group(1))] if table else [],
    )


def failures(caps: list[str], rows: list[tuple[str, frozenset[str]]], registry) -> list[str]:
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
    keys = [k for k, _ in rows]
    if sorted(keys) != sorted(p.key for p in registry):
        out.append(f"table keys {sorted(keys)} != registry keys {sorted(p.key for p in registry)}")
    lacks = dict(rows)
    if lacks.get("onlyfans"):
        out.append(f"onlyfans lacks {sorted(lacks['onlyfans'])}")
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
    print(f"{len(caps)} Capabilities, rows {[(k, len(v)) for k, v in rows]}")
    problems = failures(caps, rows, platforms.ALL)
    assert not problems, f"{len(problems)} drift failures:\n  " + "\n  ".join(problems)


class _AllRefused:
    pass


class _PinBuilt:
    def pin_message(self):
        return {}


_OF = SimpleNamespace(key="onlyfans", backend=None)
_ALL_CAPS = [*CAP_METHODS, *APP_ONLY]


def _registry(shim) -> tuple:
    return (_OF, SimpleNamespace(key="fake", backend=SimpleNamespace(Shim=shim)))


def _rows(lacks) -> list[tuple[str, frozenset[str]]]:
    return [("onlyfans", frozenset()), ("fake", frozenset(lacks))]


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
    got = failures(_ALL_CAPS, [*_rows(_ALL_CAPS), ("other", frozenset())], _registry(_AllRefused))
    assert got == ["table keys ['fake', 'onlyfans', 'other'] != registry keys ['fake', 'onlyfans']"], got


def case_onlyfans_lacking_fails():
    rows = [("onlyfans", frozenset({"block"})), ("fake", frozenset(_ALL_CAPS))]
    assert failures(_ALL_CAPS, rows, _registry(_AllRefused)) == ["onlyfans lacks ['block']"]


if __name__ == "__main__":
    _harness.run()
