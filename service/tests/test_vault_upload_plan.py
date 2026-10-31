#!/usr/bin/env python3
"""Vault import's pure half (`vault_upload_plan`) — table tests, plain asserts,
no pytest, no network. Plus `vault_upload._admit` (which feeds `_apply_caps`)
with `_save` patched, against files in a temp dir.

Run: ./venv/bin/python service/tests/test_vault_upload_plan.py
"""
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media_prep          # noqa: E402
import vault_upload        # noqa: E402
import vault_upload_plan as plan  # noqa: E402


@contextmanager
def ffmpeg(present: bool):
    """`can_shrink` asks `have_ffmpeg`; pin it so the video rows mean the same
    thing on every box, and put it back after."""
    orig = media_prep.have_ffmpeg
    media_prep.have_ffmpeg = lambda: present
    try:
        yield
    finally:
        media_prep.have_ffmpeg = orig


failures: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


MB = 1024 * 1024
# Compress hatch ON (threshold under COMPRESS_OFF_MB, target under the upload
# cap): the only setting in which `checked()` keeps a download cap above the
# upload cap, which the video rows below need.
LIM = plan.Limits(max_files=2, max_bytes=10 * MB, max_download_bytes=50 * MB,
                  compress_over_bytes=5 * MB, target_bytes=9 * MB).checked()
check("LIM: compress on", LIM.compress_enabled, True)
check("LIM: checked() keeps the caps",
      (LIM.max_files, LIM.max_bytes, LIM.max_download_bytes, LIM.target_bytes),
      (2, 10 * MB, 50 * MB, 9 * MB))

print("re-exports")
for name in ("MAX_BYTES", "MAX_FILES", "MAX_MB", "Limits", "_apply_caps", "_item",
             "cap_for", "drive_meta", "fan_handle", "parse_meta", "parse_metas",
             "resolve_budget"):
    check(f"vault_upload.{name} is the plan's", getattr(vault_upload, name),
          getattr(plan, name))

print("cap_for")
CAP_ROWS = [
    ("image mime → upload cap", "a.mp4", "image/jpeg", LIM.max_bytes),
    ("video mime → download cap", "a.jpg", "video/mp4", LIM.max_download_bytes),
    ("audio mime → upload cap", "a.mp4", "audio/mpeg", LIM.max_bytes),
    ("unknown mime, video ext → download cap", "a.MOV", "application/octet-stream",
     LIM.max_download_bytes),
    ("no mime, video ext → download cap", "clip.mp4", None, LIM.max_download_bytes),
    ("no mime, image ext → upload cap", "pic.png", None, LIM.max_bytes),
    ("no mime, no ext → upload cap", "noext", None, LIM.max_bytes),
]
with ffmpeg(True):
    for label, name, mime, want in CAP_ROWS:
        check(label, plan.cap_for(name, mime, LIM), want)
with ffmpeg(False):
    for label, name, mime in [("no ffmpeg: video mime → upload cap", "a.mp4", "video/mp4"),
                              ("no ffmpeg: video ext → upload cap", "clip.mov", None)]:
        check(label, plan.cap_for(name, mime, LIM), LIM.max_bytes)
check("resolve_budget = 2× max_files", plan.resolve_budget(LIM), 4)


def items(*specs):
    return [plan._item(n, None, "local", s) for n, s in specs]


print("_apply_caps")
CAPS_ROWS = [
    ("all fit", [("a.jpg", MB), ("b.jpg", MB)], 0, ["pending", "pending"], 2),
    ("batch cap hit", [("a.jpg", MB), ("b.jpg", MB), ("c.jpg", MB)], 0,
     ["pending", "pending", "skipped"], 2),
    ("already admitted counts", [("a.jpg", MB), ("b.jpg", MB)], 1,
     ["pending", "skipped"], 2),
    ("budget exhausted before start", [("a.jpg", MB)], 2, ["skipped"], 2),
    ("oversize image skipped, not counted", [("big.jpg", 11 * MB), ("a.jpg", MB)], 0,
     ["skipped", "pending"], 1),
    ("video under download cap admitted", [("v.mp4", 40 * MB)], 0, ["pending"], 1),
    ("video over download cap skipped", [("v.mp4", 51 * MB)], 0, ["skipped"], 0),
    ("unknown size admitted", [("a.jpg", None)], 0, ["pending"], 1),
]
with ffmpeg(True):
    for label, specs, already, want_status, want_n in CAPS_ROWS:
        its = items(*specs)
        n = plan._apply_caps(its, LIM, already=already)
        check(f"{label}: statuses", [i["status"] for i in its], want_status)
        check(f"{label}: tally", n, want_n)
    done = items(("a.jpg", MB))
    done[0]["status"] = "done"
    check("non-pending untouched and uncounted",
          (plan._apply_caps(done, LIM), done[0]["status"]), (0, "done"))
    its = items(("big.jpg", 11 * MB))
    plan._apply_caps(its, LIM)
    check("oversize error names the cap", "exceeds the 10 MB limit" in its[0]["error"], True)
with ffmpeg(False):
    its = items(("v.mp4", 11 * MB))
    plan._apply_caps(its, LIM)
    check("no ffmpeg: 11 MB video skipped at the upload cap",
          (its[0]["status"], its[0]["error"].startswith("12 MB exceeds the 10 MB limit")),
          ("skipped", True))
    check("no ffmpeg: error says ffmpeg cannot prepare it",
          its[0]["error"].endswith(" and is not video ffmpeg can prepare"), True)

print("vault_upload._admit")
with tempfile.TemporaryDirectory() as td:
    a, b, c = (str(Path(td) / n) for n in ("a.jpg", "b.jpg", "c.jpg"))
    for p in (a, b, c):
        Path(p).write_bytes(b"x" * 10)
    gone = str(Path(td) / "gone.jpg")
    saved: list = []
    orig_save = vault_upload._save
    vault_upload._save = saved.append
    try:
        for label, group, already, want_status, want_n, want_saves in [
            ("empty group: no save, tally unchanged", [], 1, [], 1, 0),
            ("dupe in group counted twice (no dedupe here)", [(a, None), (a, None)],
             0, ["pending", "pending"], 2, 1),
            ("already admitted", [(a, None), (b, None)], 1, ["pending", "skipped"], 2, 1),
            ("cap hit", [(a, None), (b, None), (c, None)], 0,
             ["pending", "pending", "skipped"], 2, 1),
        ]:
            saved.clear()
            state = {"admitted": already, "items": [{"status": "done"}]}
            got = vault_upload._admit(state, group, LIM)
            new = state["items"][1:]
            check(f"{label}: statuses", [i["status"] for i in new], want_status)
            check(f"{label}: tally", state["admitted"], want_n)
            check(f"{label}: returns only the admitted", got,
                  [i for i in new if i["status"] == "pending"])
            check(f"{label}: saves", len(saved), want_saves)
        state = {"admitted": 0, "items": []}
        got = vault_upload._admit(state, [(a, {"notes": "n"}), (gone, {})], LIM)
        it0, it1 = state["items"]
        check("item shape", (it0["name"], it0["path"], it0["source"], it0["size"], it0["meta"]),
              ("a.jpg", a, "local", 10, {"notes": "n"}))
        check("missing file: size None, empty meta → None", (it1["size"], it1["meta"]),
              (None, None))
    finally:
        vault_upload._save = orig_save

print("_price_cents / parse_meta")
# The wire is already cents (the card does Math.round(dollars * 100),
# app/components/vault/VaultImportDetails.tsx:60-61). "9.99" → 9 pins truncation
# of a fractional cents string; it is not a dollars → cents conversion.
for raw, want in [("9.99", 9), (999, 999), ("0", 0), (0, 0), ("-5", 0), (-5, 0),
                  ("abc", None), (None, None), ("", None), ([1], None)]:
    check(f"_price_cents({raw!r})", plan._price_cents(raw), want)
for label, raw, want in [
    ("not a dict", "x", None),
    ("empty dict", {}, None),
    ("unknown keys dropped", {"evil": 1}, None),
    ("price kept as cents", {"price_cents": "999"}, {"price_cents": 999}),
    ("price 0 kept", {"price_cents": "0"}, {"price_cents": 0}),
    ("negative price → 0", {"price_cents": -1}, {"price_cents": 0}),
    ("garbage price dropped", {"price_cents": "free"}, None),
    ("tags lose # and @", {"hashtags": ["#a"], "tag_creators": ["@b"]},
     {"hashtags": ["a"], "tag_creators": ["b"]}),
    ("tags must be a list", {"hashtags": "a,b"}, None),
    ("notes trimmed, capped", {"notes": "  " + "n" * 2100},
     {"notes": "n" * 2000}),
    ("list_id int", {"list_id": "7"}, {"list_id": 7}),
    ("list_id garbage dropped", {"list_id": "x"}, None),
]:
    check(f"parse_meta: {label}", plan.parse_meta(raw), want)

print("parse_metas")
for label, raw, want in [
    ("None", None, []),
    ("empty", "", []),
    ("bad JSON", "{nope", []),
    ("JSON object, not list", '{"notes": "x"}', []),
    ("list, entry per file", '[{"price_cents": 5}, null, "x"]',
     [{"price_cents": 5}, None, None]),
]:
    check(f"parse_metas: {label}", plan.parse_metas(raw), want)

print("fan_handle")
for raw, want in [("name", "name"), ("@name", "name"), ("  @na.me_1 ", "na.me_1"),
                  ("https://onlyfans.com/name", "name"),
                  ("https://OnlyFans.com//name/?ref=x", "name"),
                  ("onlyfans.com/name/media", "name"),
                  ("", ""), (None, ""), ("@", "")]:
    check(f"fan_handle({raw!r})", plan.fan_handle(raw), want)
for raw in ("two words", "bad!name", "x" * 65):
    try:
        plan.fan_handle(raw)
        check(f"fan_handle({raw[:12]!r}) raises", "no raise", "ValueError")
    except ValueError:
        check(f"fan_handle({raw[:12]!r}) raises", "ValueError", "ValueError")

print()
if failures:
    print(f"❌ {len(failures)} FAILED")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ all vault upload plan tests passed")
