#!/usr/bin/env python3
"""deploy/ae/ae-fence keeps AE's bio container down with the relay and app (it runs the relay image on the same DB),
and a box without one (bio not started there) fences as before: a fake `docker`/`pgrep` on PATH and a fake docker
root, no daemon.

Run: ./venv/bin/python service/tests/test_ae_fence.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

FENCE = Path(__file__).resolve().parents[2] / "deploy/ae/ae-fence"
# `docker ps/inspect/update <names>` against $FAKE_EXISTING; every call logged. Like docker, update fails for a
# missing name (after updating the others). FAKE_DOWN=1: the daemon is unreachable, every call fails.
DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
[ -n "${FAKE_DOWN:-}" ] && { echo "Cannot connect to the Docker daemon" >&2; exit 1; }
cmd=$1; shift
[ "$cmd" = ps ] && { printf '%s\\n' $FAKE_EXISTING; exit 0; }
names=(); for a in "$@"; do case "$a" in -*|*'{{'*) ;; *) names+=("$a") ;; esac; done
rc=0
for n in "${names[@]}"; do case " $FAKE_EXISTING " in *" $n "*) ;; *) rc=1 ;; esac; done
[ "$cmd" = inspect ] && [ "$rc" = 0 ] && case "$*" in *Running*) echo false ;; esac
exit $rc
"""


def _env(existing: str) -> tuple[dict, Path]:
    d = Path(tempfile.mkdtemp(prefix="ae_fence_"))
    (d / "bin").mkdir()
    (d / "bin" / "docker").write_text(DOCKER)
    (d / "bin" / "pgrep").write_text("#!/bin/sh\nexit 1\n")  # dockerd down
    for f in ("docker", "pgrep"):
        (d / "bin" / f).chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AE_FENCE")}
    env.update(PATH=f"{d / 'bin'}:{os.environ['PATH']}", FAKE_LOG=str(d / "docker.log"), FAKE_EXISTING=existing,
               AE_FENCE_MARK=str(d / "mark"), AE_FENCE_LOG=str(d / "fence.log"), AE_FENCE_ASK="echo active=yes",
               AE_DOCKER_ROOT=str(d / "docker"))
    for i, name in enumerate(existing.split()):
        c = d / "docker" / "containers" / f"{i:064d}"
        c.mkdir(parents=True)
        (c / "config.v2.json").write_text(json.dumps({"Name": "/" + name}))
        (c / "hostconfig.json").write_text(json.dumps({"RestartPolicy": {"Name": "unless-stopped"}}))
    return env, d


def _run(env, *args):
    return subprocess.run(["bash", str(FENCE), *args], env=env, capture_output=True, text=True, timeout=30)


def _policies(d: Path) -> dict:
    out = {}
    for c in (d / "docker" / "containers").iterdir():
        name = json.loads((c / "config.v2.json").read_text())["Name"].lstrip("/")
        out[name] = json.loads((c / "hostconfig.json").read_text())["RestartPolicy"]["Name"]
    return out


def case_boot_fences_bio_with_relay_and_app():
    env, d = _env("ae-relay ae-app ae-bio ae-autoheal")
    r = _run(env, "boot")
    assert r.returncode == 0, r.stderr
    assert _policies(d) == {"ae-relay": "no", "ae-app": "no", "ae-bio": "no", "ae-autoheal": "unless-stopped"}, \
        _policies(d)


def case_arm_and_post_cover_bio_and_skip_it_when_absent():
    for existing, want in (("ae-relay ae-app ae-bio", "ae-relay ae-app ae-bio"), ("ae-relay ae-app", "ae-relay ae-app")):
        env, d = _env(existing)
        r = _run(env, "arm", "test")
        assert r.returncode == 0, (existing, r.stderr)
        updated = [ln.split()[-1] for ln in (d / "docker.log").read_text().splitlines()
                   if ln.startswith("update --restart=no")]
        assert updated == want.split(), (existing, updated)
        (d / "docker.log").unlink()
        r = _run(env, "post")
        assert r.returncode == 0, (existing, r.stderr)
        updated = [ln.split()[-1] for ln in (d / "docker.log").read_text().splitlines() if ln.startswith("update")]
        assert updated == want.split(), (existing, updated)


def case_arm_fails_when_docker_cannot_list():
    # Docker down: arm must not report restart=no for containers it never reached (marker still written, as before)
    env, d = _env("ae-relay ae-app ae-bio")
    env["FAKE_DOWN"] = "1"
    r = _run(env, "arm", "test")
    assert r.returncode != 0, (r.returncode, r.stderr)
    assert (d / "mark").exists()
    assert "restart=no (still running" not in (d / "fence.log").read_text(), (d / "fence.log").read_text()


_harness.run()
