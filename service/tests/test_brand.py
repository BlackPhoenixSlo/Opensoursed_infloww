"""BRAND_NAME (service/brand.py) renames the product wherever the relay says it.

Unset: Inflowwww, as before. Set (a deployment's .env, e.g. Acme Desk): the TOTP issuer, the
help assistant's prompt and the proxy pool's messages say that name instead.
The override runs in a child process, since the name is read at import.

Run: ./venv/bin/python service/tests/test_brand.py
"""
import _harness  # MUST be first: binds a throwaway temp DB

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

TESTS = Path(__file__).resolve().parent

PROBE = """
import _harness
import account_security, assistant_api, proxies, server
print(account_security.otpauth_uri("ann", "ABC"))
print(server.POOL_PROXY_ERROR)
p = assistant_api._build_system_prompt()
print("prompt-has-name", "Acme Desk" in p, "prompt-has-old", "Inflowwww" in p)
"""


def _probe(env_extra: dict[str, str]) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k != "BRAND_NAME"} | env_extra
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=TESTS, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip().splitlines()[-3:]


def case_default_is_inflowwww():
    uri, err, prompt = _probe({})
    assert uri.startswith("otpauth://totp/Inflowwww%3Aann?secret=ABC&issuer=Inflowwww"), uri
    assert err == "Inflowwww proxy unreachable", err
    assert prompt == "prompt-has-name False prompt-has-old True", prompt


def case_env_renames_everything_the_relay_says():
    uri, err, prompt = _probe({"BRAND_NAME": "Acme Desk"})
    assert uri.startswith("otpauth://totp/Acme%20Desk%3Aann?secret=ABC&issuer=Acme%20Desk"), uri
    assert err == "Acme Desk proxy unreachable", err
    assert prompt == "prompt-has-name True prompt-has-old False", prompt


_harness.run()
