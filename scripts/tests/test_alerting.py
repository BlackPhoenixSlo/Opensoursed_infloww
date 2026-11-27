import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
NOTIFY = SCRIPTS / "notify.sh"
WATCHDOG = SCRIPTS / "vps-watchdog.sh"
INSTALLER = SCRIPTS / "watchdog.sh"

CURL_STUB = r"""#!/usr/bin/env bash
printf "%s\n" "${*//$'\n'/ }" >> "$CURL_LOG"
fail=0
for a in "$@"; do
  case "$a" in --fail) fail=1 ;; --*) ;; -*f*) fail=1 ;; esac
done
code="${STUB_HTTP_CODE:-200}"
for a in "$@"; do
  if [ "$a" = -K ]; then
    config=$(cat)
    printf "%s\n" "$config" >> "$CURL_LOG.stdin"
    if [[ "$config" = *callmebot* ]]; then code="${STUB_WHATSAPP_CODE:-$code}"; fi
    break
  fi
done
default_body='{"ok":true}'
if [[ "${config:-}" = *'/getUpdates'* ]]; then
  n=$(grep -c '/getUpdates' "$CURL_LOG.stdin")
  if [ -f "$HOME/updates.$n" ]; then
    STUB_BODY=$(cat "$HOME/updates.$n")
  elif [ "$n" -eq 1 ] && [[ "$config" = *'/getUpdates?offset='* ]] && [ "${STUB_BODY:-}" != '{"ok":false}' ]; then
    STUB_BODY='{"ok":true,"result":[]}'
  fi
fi
case " $* " in
  *' -o /dev/null '*) ;;
  *) printf "%s" "${STUB_BODY:-$default_body}" ;;
esac
for a in "$@"; do
  if [ "$a" = -w ]; then printf '%s' "$code"; break; fi
done

if [ "$code" -ge 400 ] && [ "$fail" -eq 1 ]; then exit 22; fi
exit 0
"""

SSH_STUB = r"""#!/usr/bin/env bash
set -e
mkdir -p "$SSH_LOG"
n=$(find "$SSH_LOG" -name '*.argv' | wc -l | tr -d ' ')
printf "%s\n" "$*" > "$SSH_LOG/$n.argv"
cat > "$SSH_LOG/$n.stdin"
rewrite() {
  local text="$1"
  text="${text//\/root\/fastt/$HOME/fastt}"
  text="${text//\/var\/lib\/fastt-watchdog/$WATCHDOG_STATE}"
  text="${text//\/var\/log\/fastt-watchdog.log/$WATCHDOG_LOG}"
  printf '%s' "${text//\/etc\/logrotate.d/$HOME/logrotate.d}"
}
cmd="$(rewrite "$2")"
input="$SSH_LOG/$n.stdin"
case "$cmd" in
  'bash -s '*)
    rewrite "$(cat "$input")" > "$input.script"
    printf '\n' >> "$input.script"
    input="$input.script"
    ;;
  'mktemp '*)
    path="$(bash -c "$cmd")"
    printf '/root/fastt%s\n' "${path#"$HOME/fastt"}"
    exit 0
    ;;
  mkdir\ *|rm\ *|python3\ *|grep\ *|docker\ *|command\ *|sed\ *|"$HOME"/fastt/scripts/*) ;;
  *)
    printf 'unexpected ssh command: %s\n' "$2" | tee -a "$SSH_LOG.unexpected" >&2
    exit 127
    ;;
esac
exec bash -c "$cmd" < "$input"
"""

DOCKER_STUB = r"""#!/usr/bin/env bash
case "$1" in
  ps)
    printf '%s\n' discovered worker
    exit "${STUB_DOCKER_PS_RC:-0}"
    ;;
  inspect) [[ "$3" != *'.Id'* ]] && echo running/healthy ;;
  *) echo "unexpected docker command: $*" >&2; exit 127 ;;
esac
"""

CRONTAB_STUB = """#!/usr/bin/env bash
case "$1" in
  -l)
    if [ "${STUB_CRON_READ_ERROR:-0}" = 1 ] && [ ! -f "$HOME/cron-written" ]; then
      echo "crontab: permission denied" >&2
      exit 1
    fi
    if [ ! -f "$HOME/crontab" ]; then
      echo "no crontab for root" >&2
      exit 1
    fi
    cat "$HOME/crontab"
    ;;
  -)
    input=$(cat)
    [ "${STUB_CRON_REJECT:-0}" = 0 ] || exit 1
    [ "${STUB_CRON_DROP:-0}" = 0 ] || exit 0
    printf '%s\\n' "$input" > "$HOME/crontab"
    : > "$HOME/cron-written"
    ;;
  *) exit 1 ;;
esac
"""

SCP_STUB = r"""#!/usr/bin/env bash
set -e
printf "%s\n" "$*" >> "$SSH_LOG.scp"
[ "$#" = 3 ] && [ "$1" = -q ] && [[ "$3" = *:/root/fastt/scripts/*.new ]] || exit 1
source="$2"
dest="$HOME/fastt/scripts/${3##*/}"
if [[ "$source" = */vps-watchdog.sh ]]; then
  if [ "${STUB_INVALID_UPLOAD:-0}" = 1 ]; then
    printf 'if\n' > "$dest"
  elif [ "${STUB_SMOKE_FAILURE:-0}" = 1 ]; then
    printf '#!/bin/bash\nexit 42\n' > "$dest"
  else
    sed "s|/proc/|$HOME/|g" "$source" > "$dest"
  fi
else
  cp "$source" "$dest"
fi
"""

CHANNELS = {
    "whatsapp": "WHATSAPP_PHONE=1\nWHATSAPP_APIKEY=k\n",
    "telegram": "TELEGRAM_TOKEN=t\nTELEGRAM_CHAT_ID=1\n",
    "webhook": "ALERT_WEBHOOK_URL=http://hook.invalid/x\n",
}


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    stub.write_text(CURL_STUB)
    stub.chmod(0o755)
    for name, body in (("ssh", SSH_STUB), ("scp", SCP_STUB), ("docker", DOCKER_STUB), ("crontab", CRONTAB_STUB)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "logrotate.d").mkdir()
    (tmp_path / "stat").write_text("cpu 1 2 3 4 5 6 7 8 9\n")
    (tmp_path / "loadavg").write_text("0.00 0.00 0.00\n")
    (tmp_path / "fastt").mkdir()
    e = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', os.defpath)}",
        "HOME": str(tmp_path),
        "CURL_LOG": str(tmp_path / "curl.log"),
        "WATCHDOG_CONFIG": str(tmp_path / "fastt" / "watchdog.env"),
        "WATCHDOG_LOG": str(tmp_path / "watchdog.log"),
        "WATCHDOG_STATE": str(state),
        "SSH_LOG": str(tmp_path / "ssh"),
        "TG_SLEEP": "0",
    }
    (tmp_path / "fastt" / "watchdog.env").write_text(CHANNELS["telegram"])
    yield e, tmp_path
    unexpected = tmp_path / "ssh.unexpected"
    assert not unexpected.exists(), unexpected.read_text() if unexpected.exists() else ""


@pytest.fixture
def no_jq(env):
    e, tmp_path = env
    tools = tmp_path / "tools"
    tools.mkdir()
    for tool in ("bash", "cat", "chmod", "cp", "cut", "date", "df", "find", "grep", "head",
                 "hostname", "dirname", "mkdir", "sleep", "stat", "sed", "tail", "tee", "tr", "wc", "awk", "xargs",
                 "md5", "md5sum", "python3", "echo"):
        if src := shutil.which(tool):
            (tools / tool).symlink_to(src)
    return {**e, "PATH": f"{tmp_path / 'bin'}:{tools}"}, tmp_path


def notify(e, code):
    return subprocess.run(
        ["bash", str(NOTIFY), "crit", "title", "body"],
        env={**e, "STUB_HTTP_CODE": str(code)}, capture_output=True, text=True, timeout=30,
    )


def transition(e, code, bad):
    script = f'. "{WATCHDOG}"; transition steal {bad} crit "CPU throttled" "b"'
    return subprocess.run(
        ["bash", "-c", script],
        env={**e, "STUB_HTTP_CODE": str(code)}, capture_output=True, text=True, timeout=30,
    )


def state_of(tmp_path):
    f = tmp_path / "state" / "steal"
    return f.read_text().strip() if f.exists() else "ok"


def test_stub_mimics_curl_without_fail_flag(env):
    e, tmp = env
    r = subprocess.run(["curl", "-sS", "http://x"], env={**e, "STUB_HTTP_CODE": "500"},
                       capture_output=True, text=True)
    assert r.returncode == 0
    r = subprocess.run(["curl", "-fsS", "http://x"], env={**e, "STUB_HTTP_CODE": "500"},
                       capture_output=True, text=True)
    assert r.returncode == 22


@pytest.mark.parametrize("channel", sorted(CHANNELS))
def test_every_channel_counts_http_error_as_not_delivered(env, channel):
    e, tmp = env
    if channel == "webhook" and not shutil.which("jq"):
        pytest.skip("webhook channel needs jq")
    (tmp / "fastt" / "watchdog.env").write_text(CHANNELS[channel])
    assert notify(e, 500).returncode != 0
    assert notify(e, 200).returncode == 0
    assert len((tmp / "curl.log").read_text().splitlines()) == 2


def test_webhook_redirect_is_not_delivered(env):
    e, tmp = env
    if not shutil.which("jq"):
        pytest.skip("webhook channel needs jq")
    (tmp / "fastt" / "watchdog.env").write_text(CHANNELS["webhook"])
    assert notify(e, 302).returncode == 3


def test_telegram_ok_false_is_not_delivered(env):
    e, _ = env
    assert notify({**e, "STUB_BODY": '{"ok":false}'}, 200).returncode == 3


@pytest.mark.parametrize("channel,key,secret", [
    ("whatsapp", "WHATSAPP_APIKEY", "private-api-key"),
    ("telegram", "TELEGRAM_TOKEN", "12345:private-token"),
    ("webhook", "ALERT_WEBHOOK_URL", "https://hook.invalid/private-url"),
])
def test_notify_keeps_secrets_off_curl_argv(env, channel, key, secret):
    e, tmp = env
    if channel == "webhook" and not shutil.which("jq"):
        pytest.skip("webhook channel needs jq")
    (tmp / "fastt" / "watchdog.env").write_text(CHANNELS[channel] + f"{key}={secret}\n")
    assert notify(e, 200).returncode == 0
    assert secret not in (tmp / "curl.log").read_text()
    assert secret in (tmp / "curl.log.stdin").read_text()


def test_notify_escapes_curl_config_values(env):
    e, tmp = env
    (tmp / "fastt" / "watchdog.env").write_text(CHANNELS["whatsapp"] + """WHATSAPP_APIKEY='key"with\\slashes'\n""")
    assert notify(e, 200).returncode == 0
    config = (tmp / "curl.log.stdin").read_text().splitlines()
    assert config[0] == "get"
    assert r'data-urlencode = "apikey=key\"with\\slashes"' in config


def test_notify_logs_webhook_without_jq(no_jq):
    e, tmp = no_jq
    (tmp / "fastt" / "watchdog.env").write_text(CHANNELS["webhook"])
    assert notify(e, 200).returncode == 3
    assert "NOT DELIVERED failed=webhook" in log(tmp)
    assert not (tmp / "curl.log").exists()


def test_notify_logs_partial_and_total_delivery_failures(env):
    e, tmp = env
    (tmp / "fastt" / "watchdog.env").write_text(CHANNELS["whatsapp"] + CHANNELS["telegram"])
    assert notify({**e, "STUB_WHATSAPP_CODE": "503"}, 200).returncode == 0
    assert notify(e, 503).returncode == 3
    assert [line.partition("title body ")[2] for line in log(tmp).splitlines()] == [
        "delivered=telegram failed=whatsapp",
        "NOT DELIVERED failed=whatsapp,telegram",
    ]


def test_failed_page_stays_pending_then_retries(env):
    e, tmp = env
    transition(e, 500, 1)
    assert state_of(tmp) == "pending"
    transition(e, 500, 1)
    assert state_of(tmp) == "pending"
    transition(e, 200, 1)
    assert state_of(tmp) == "bad"
    assert len((tmp / "curl.log").read_text().splitlines()) == 3
    transition(e, 200, 1)
    assert len((tmp / "curl.log").read_text().splitlines()) == 3


def test_short_outage_reports_recovery_after_failed_initial_alert(env):
    e, tmp = env
    transition(e, 500, 1)
    transition(e, 500, 0)
    assert state_of(tmp) == "pending"
    transition(e, 200, 0)
    assert state_of(tmp) == "ok"
    transition(e, 200, 0)
    log = (tmp / "curl.log.stdin").read_text()
    assert log.count("RECOVERED (alert was not delivered earlier): CPU throttled") == 2
    assert len((tmp / "curl.log").read_text().splitlines()) == 3


def test_failed_recovery_page_retries(env):
    e, tmp = env
    (tmp / "state" / "steal").write_text("bad\n")
    transition(e, 500, 0)
    assert state_of(tmp) == "bad"
    transition(e, 200, 0)
    assert state_of(tmp) == "ok"
    log = (tmp / "curl.log.stdin").read_text()
    assert log.count("RECOVERED") == 2


def test_interrupted_first_alert_leaves_pending(env):
    e, tmp = env
    sender = tmp / "notify.sh"
    sender.write_text('#!/bin/bash\nkill -KILL "$PPID"\n')
    sender.chmod(0o755)
    r = subprocess.run(
        ["bash", "-c", f'. "{WATCHDOG}"; NOTIFY="$1"; transition steal 1 crit "CPU throttled"', "_", str(sender)],
        env=e, capture_output=True, timeout=30,
    )
    assert r.returncode == -9
    assert state_of(tmp) == "pending"
    r = transition(e, 200, 0)
    assert r.returncode == 0
    assert state_of(tmp) == "ok"
    assert "RECOVERED" in (tmp / "curl.log.stdin").read_text()


def test_transition_logs_state_write_failure(env):
    e, tmp = env
    blocked = tmp / "state" / "steal"
    blocked.mkdir()
    r = transition(e, 200, 1)
    expected = f"state write failed: {blocked}"
    assert r.stderr == ""
    assert log(tmp).splitlines().count(expected) == 1


TOKEN = "123456:ABCdef_ghi-JKL"
UPDATES = """{"ok":true,"result":[
  {"update_id":3,"message":{"text":"hello","chat":{"id":666}}},
  {"update_id":2,"message":{"text":"  Hi ","chat":{"id":-4242,"title":"ops"}}},
  {"update_id":1,"message":{"text":"hi","chat":{"id":111}}},
  {"update_id":4,"edited_message":{"text":"hi","chat":{"id":777}}}
]}"""


def run_installer(e, args, stdin="", *, prefix=(), **extra):
    return subprocess.run([*prefix, "/bin/bash", str(INSTALLER), *args], input=stdin, env={**e, **extra},
                          capture_output=True, text=True, timeout=30)


def ssh_calls(tmp):
    d = tmp / "ssh"
    if not d.exists():
        return []
    return [((d / f"{i}.argv").read_text(), (d / f"{i}.stdin").read_text())
            for i in range(len(list(d.glob("*.argv"))))]


def test_telegram_finds_latest_chat_id_and_keeps_token_off_argv(env):
    e, tmp = env
    r = run_installer(e, ["root@box.example", "telegram"], TOKEN + "\n", STUB_BODY=UPDATES)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "found chat id -4242 (ops)" in r.stdout
    assert "✅ delivered" in r.stdout
    calls = ssh_calls(tmp)
    assert all(a.startswith("root@box.example ") for a, _ in calls)
    assert sourced_config(e, "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID") == [TOKEN, "-4242"]
    assert "notify.sh ok" in calls[-1][0]
    assert any(TOKEN in stdin for _, stdin in calls)
    argv = (tmp / "curl.log").read_text() + "".join(a for a, _ in calls)
    assert TOKEN not in argv
    assert TOKEN in (tmp / "curl.log.stdin").read_text()


def test_telegram_skips_backlog_and_pages_until_fresh_hi(env):
    e, tmp = env
    pages = [
        '{"ok":true,"result":[{"update_id":100,"message":{"text":"hi","chat":{"id":111}}}]}',
        '{"ok":true,"result":[{"update_id":200,"message":{"text":"hi","chat":{"id":222}}}]}',
        '{"ok":true,"result":[]}',
        '{"ok":true,"result":[{"update_id":201,"message":{"text":"hello","chat":{"id":333}}}]}',
        '{"ok":true,"result":[{"update_id":202,"message":{"text":"hi","chat":{"id":444}}}]}',
    ]
    for i, page in enumerate(pages, 1):
        (tmp / f"updates.{i}").write_text(page)
    r = run_installer(e, ["root@h", "telegram"], TOKEN + "\n", TG_TRIES="3")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sourced_config(e, "TELEGRAM_CHAT_ID") == ["444"]
    requests = (tmp / "curl.log.stdin").read_text().splitlines()
    assert [line.split("offset=")[-1].strip('"') for line in requests if "/getUpdates" in line] == [
        "0", "101", "201", "201", "202",
    ]


def test_telegram_without_message_writes_nothing(env):
    e, tmp = env
    r = run_installer(e, ["root@box.example", "telegram"], TOKEN + "\n",
                      STUB_BODY='{"ok":true,"result":[]}', TG_TRIES="2")
    assert r.returncode != 0
    assert "no message reached the bot" in r.stdout
    assert len((tmp / "curl.log").read_text().splitlines()) == 3
    assert ssh_calls(tmp) == []


def test_telegram_rejected_token_stops_polling_immediately(env):
    e, tmp = env
    r = run_installer(e, ["root@h", "telegram"], TOKEN + "\n",
                      STUB_BODY='{"ok":false}', TG_TRIES="3")
    assert r.returncode != 0
    assert "token rejected" in r.stdout
    assert len((tmp / "curl.log").read_text().splitlines()) == 1
    assert ssh_calls(tmp) == []


def test_telegram_rejects_non_token(env):
    e, tmp = env
    r = run_installer(e, ["root@box.example", "telegram"], "hello\n")
    assert r.returncode != 0
    assert not (tmp / "curl.log").exists()


def test_telegram_reports_not_delivered(env):
    e, tmp = env
    r = run_installer(e, ["root@box.example", "telegram"], TOKEN + "\n", STUB_BODY=UPDATES, STUB_HTTP_CODE="503")
    assert r.returncode == 3
    assert "not delivered" in r.stdout


def test_channel_setup_tests_only_the_selected_channel(env):
    e, tmp = env
    scripts = tmp / "fastt" / "scripts"
    scripts.mkdir()
    stale = scripts / "notify.sh"
    stale.write_text('#!/bin/bash\nexec "$(dirname "$0")/legacy-notify.sh" "${@:1:3}"\n')
    stale.chmod(0o755)
    shutil.copy2(NOTIFY, scripts / "legacy-notify.sh")
    r = run_installer(e, ["root@h", "whatsapp"], "12345678\nsecret\n", STUB_WHATSAPP_CODE="503")
    assert r.returncode == 3
    assert "❌ not delivered" in r.stdout
    assert "✅ delivered" not in r.stdout
    assert "sendMessage" not in (tmp / "curl.log.stdin").read_text()


def test_webhook_requires_remote_jq_before_saving(no_jq):
    e, tmp = no_jq
    r = run_installer(e, ["root@h", "webhook"], "https://hook.invalid/token\n")
    assert r.returncode != 0
    assert "requires jq" in r.stderr
    assert sourced_config(e, "ALERT_WEBHOOK_URL") == [""]


@pytest.mark.parametrize("args", [[], ["-x", "install"], *(
    [mode] for mode in ("status", "show", "install", "telegram", "whatsapp", "webhook", "test", "clear")
)])
def test_host_is_required_first(env, args):
    e, tmp = env
    r = run_installer(e, args)
    assert r.returncode == 1
    assert "Usage" in r.stdout
    assert ssh_calls(tmp) == []


def sourced_config(e, *keys):
    r = subprocess.run(
        ["bash", "-c", '. "$WATCHDOG_CONFIG"; for k; do printf "%s\\0" "${!k}"; done', "_", *keys],
        env=e, capture_output=True, text=True, check=True, timeout=30,
    )
    return r.stdout.split("\0")[:-1]


def test_install_sets_urls_and_containers_from_flags(env):
    e, tmp = env
    r = run_installer(e, ["admin@10.0.0.9", "install", "--url", "https://a.example/",
                          "--url", "https://b.example/livez", "--containers", "web db"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert sourced_config(e, "PUBLIC_URLS", "WATCH_CONTAINERS") == [
        "https://a.example/ https://b.example/livez", "web db",
    ]
    uploads = (tmp / "ssh.scp").read_text().splitlines()
    assert len(uploads) == 2
    assert all(" admin@10.0.0.9:/root/fastt/scripts/" in line and line.endswith(".new") for line in uploads)
    assert all(a.startswith("admin@10.0.0.9 ") for a, _ in ssh_calls(tmp))


def test_install_takes_env_and_leaves_keys_alone_without_them(env):
    e, _ = env
    r = run_installer(e, ["root@h", "install"], PUBLIC_URLS="https://env.example/", WATCH_CONTAINERS="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sourced_config(e, "PUBLIC_URLS", "WATCH_CONTAINERS") == ["https://env.example/", ""]
    r = run_installer(e, ["root@h", "install"])
    assert r.returncode == 0
    assert sourced_config(e, "PUBLIC_URLS", "WATCH_CONTAINERS") == ["https://env.example/", ""]


def test_reinstall_replaces_discovered_containers_and_all_duplicate_keys(env):
    e, tmp = env
    cfg = tmp / "fastt" / "watchdog.env"
    cfg.write_text('#WATCH_CONTAINERS="example"\n')
    args = ["root@h", "install"]
    r = run_installer(e, args)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sourced_config(e, "WATCH_CONTAINERS") == ["discovered worker"]
    r = run_installer(e, args + ["--containers", "new worker"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert sourced_config(e, "WATCH_CONTAINERS") == ["new worker"]
    assert cfg.read_text().count("WATCH_CONTAINERS=") == 1


@pytest.mark.parametrize("mode,data", [("whatsapp", "12345678\nsecret\n"), ("install", "")])
def test_config_write_failure_blocks_setup_success(env, mode, data):
    e, tmp = env
    config = tmp / "fastt" / "watchdog.env"
    (config.parent / "scripts").mkdir()
    prefix = ("setpriv", "--bounding-set=-dac_override,-dac_read_search") if os.geteuid() == 0 else ()
    config.parent.chmod(0o555)
    try:
        r = run_installer(e, ["root@h", mode], data, prefix=prefix)
    finally:
        config.parent.chmod(0o755)
    assert "PermissionError" in r.stderr, r.stdout + r.stderr
    assert config.read_text() == CHANNELS["telegram"]
    assert r.returncode != 0
    assert "❌ could not write" in r.stderr
    assert "✅ delivered" not in r.stdout
    assert all("notify.sh ok" not in argv for argv, _ in ssh_calls(tmp))


@pytest.mark.parametrize("failure", ["STUB_CRON_REJECT", "STUB_CRON_DROP", None])
def test_install_verifies_watchdog_cron(env, failure):
    e, tmp = env
    existing = "# existing cron\n# vps-watchdog.sh maintenance notes\n0 0 * * * /usr/bin/true\n"
    (tmp / "crontab").write_text(existing)
    extra = {failure: "1"} if failure else {}
    r = run_installer(e, ["root@h", "install"], **extra)
    if failure:
        assert r.returncode != 0
        assert "❌ could not install watchdog cron" in r.stderr
        assert "cron: every 3 min" not in r.stdout
        assert "✅ delivered" not in r.stdout
    else:
        assert r.returncode == 0, r.stderr
        assert "cron: every 3 min" in r.stdout
        assert (tmp / "crontab").read_text().startswith(existing)
        assert (tmp / "crontab").read_text().endswith(f"*/3 * * * * {tmp}/fastt/scripts/vps-watchdog.sh >> {tmp}/watchdog.log 2>&1\n")


def test_install_replaces_old_watchdog_cron(env):
    e, tmp = env
    cron = tmp / "crontab"
    watchdog = tmp / "fastt" / "scripts" / "vps-watchdog.sh"
    unrelated = "0 0 * * * /usr/bin/true"
    cron.write_text(f"*/10 * * * * {watchdog} >/dev/null 2>&1\n{unrelated}\n")
    r = run_installer(e, ["root@h", "install"])
    assert r.returncode == 0, r.stderr
    assert cron.read_text().splitlines() == [
        unrelated,
        f"*/3 * * * * {watchdog} >> {tmp}/watchdog.log 2>&1",
    ]


def test_install_aborts_on_crontab_read_error(env):
    e, tmp = env
    cron = tmp / "crontab"
    cron.write_text("# existing cron\n")
    r = run_installer(e, ["root@h", "install"], STUB_CRON_READ_ERROR="1")
    assert r.returncode != 0
    assert "❌ could not read crontab" in r.stderr
    assert cron.read_text() == "# existing cron\n"


def test_setup_preserves_live_scripts_when_staged_upload_is_invalid(env):
    e, tmp = env
    scripts = tmp / "fastt" / "scripts"
    scripts.mkdir()
    originals = {"notify.sh": "#!/bin/bash\nexit 0\n", "vps-watchdog.sh": "#!/bin/bash\nexit 2\n"}
    for name, original in originals.items():
        (scripts / name).write_text(original)
        (scripts / name).chmod(0o755)
    r = run_installer(e, ["root@h", "whatsapp"], "12345678\nsecret\n", STUB_INVALID_UPLOAD="1")
    assert {name: (scripts / name).read_text() for name in originals} == originals
    assert r.returncode != 0
    assert "❌ could not install watchdog scripts" in r.stderr
    assert sourced_config(e, "WHATSAPP_PHONE") == [""]


def test_install_retries_docker_discovery_after_error(env):
    e, tmp = env
    args = ["root@h", "install"]
    r = run_installer(e, args, STUB_DOCKER_PS_RC="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WATCH_CONTAINERS=" not in (tmp / "fastt" / "watchdog.env").read_text()
    assert "could not list containers; re-run with --containers" in r.stderr
    r = run_installer(e, args)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sourced_config(e, "WATCH_CONTAINERS") == ["discovered worker"]


def test_install_reports_smoke_failure(env):
    e, tmp = env
    r = run_installer(e, ["root@h", "install"], STUB_SMOKE_FAILURE="1")
    assert r.returncode != 0
    assert "❌ watchdog smoke run failed" in r.stderr
    assert not (tmp / "curl.log").exists()


@pytest.mark.parametrize("configured", [True, False])
def test_install_distinguishes_failed_delivery_from_unconfigured(env, configured):
    e, tmp = env
    if not configured:
        (tmp / "fastt" / "watchdog.env").unlink()
    r = run_installer(e, ["root@h", "install"], STUB_HTTP_CODE="503")
    if configured:
        assert r.returncode == 3
        assert "❌ not delivered" in r.stdout
        assert "no channel yet" not in r.stdout
    else:
        assert r.returncode == 0
        assert "no channel yet" in r.stdout
        assert "❌ not delivered" not in r.stdout


def test_install_rejects_unknown_flag(env):
    e, tmp = env
    r = run_installer(e, ["root@h", "install", "--urls", "x"])
    assert r.returncode == 1
    assert ssh_calls(tmp) == []


def test_config_writer_quotes_values_and_replaces_file_atomically(env):
    e, tmp = env
    cfg = tmp / "fastt" / "watchdog.env"
    cfg.write_text("#WHATSAPP_APIKEY=\nKEEP=1\n")
    cfg.chmod(0o644)
    secret = "x'$(touch pwned)"
    with cfg.open() as previous:
        r = run_installer(e, ["root@h", "whatsapp"], f"12345678\n{secret}\n")
        assert r.returncode == 0, r.stderr
        assert previous.read() == "#WHATSAPP_APIKEY=\nKEEP=1\n"
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    assert sourced_config(e, "WHATSAPP_APIKEY", "KEEP") == [secret, "1"]
    assert all(secret not in argv for argv, _ in ssh_calls(tmp))
    assert cfg.read_text().count("WHATSAPP_APIKEY=") == 1


def test_status_includes_masked_channels_probes_and_recent_log(env):
    e, tmp = env
    secrets = ["12345:private-token", "-4242", "12345678", "api-secret", "https://hook.invalid/secret"]
    keys = ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "WHATSAPP_PHONE", "WHATSAPP_APIKEY", "ALERT_WEBHOOK_URL"]
    (tmp / "fastt" / "watchdog.env").write_text(
        "#TELEGRAM_TOKEN=old\n" + "".join(f"{k}={v}\n" for k, v in zip(keys, secrets))
        + "PUBLIC_URLS='https://a.invalid https://b.invalid'\nWATCH_CONTAINERS='web db'\n"
    )
    (tmp / "watchdog.log").write_text("old entry\n" + "recent entry\n" * 5)
    r = run_installer(e, ["root@h", "status"])
    assert r.returncode == 0, r.stderr
    assert all(key in r.stdout for key in keys)
    assert all(secret not in r.stdout for secret in secrets)
    assert "https://a.invalid https://b.invalid" in r.stdout
    assert "web db" in r.stdout
    assert r.stdout.count("recent entry") == 5
    assert "old entry" not in r.stdout
    assert len(ssh_calls(tmp)) == 1


@pytest.mark.parametrize("config", ["", "PUBLIC_URL=https://a.invalid", "PUBLIC_URLS=https://a.invalid",
                                    "WATCH_CONTAINERS=web", "SHARDS=s01\nOI_BACKUP_CHECKS=0"])
def test_watchdog_logs_missing_probe_configuration_once_per_run(env, config):
    e, tmp = env
    (tmp / "fastt" / "watchdog.env").write_text(config + "\n")
    watchdog = tmp / WATCHDOG.name
    watchdog.write_text(WATCHDOG.read_text().replace("/proc/", f"{tmp}/"))
    (tmp / NOTIFY.name).symlink_to(NOTIFY)
    r = subprocess.run(["bash", str(watchdog)], env=e, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert log(tmp).count("no site/containers configured — not probed") == (0 if config else 1)


NOW = 1_800_000_000
SH = "s01"
SLEEP_STUB = r"""#!/usr/bin/env bash
echo "$1" >> "$SLEEP_LOG"
exit 0
"""
LAG_STUB = r"""#!/usr/bin/env bash
echo "$* LITESTREAM_ACCESS_KEY_ID=${LITESTREAM_ACCESS_KEY_ID:-}" >> "$LAG_LOG"
v="$(head -1 "$LAG_SEQ")"; [ "$(wc -l < "$LAG_SEQ")" -gt 1 ] && sed -i.bak 1d "$LAG_SEQ"
[ "$v" = fail ] && { echo "bucket down" >&2; exit 3; }
echo "$v"
"""


def age(path, seconds):
    os.utime(path, (NOW - seconds, NOW - seconds))


@pytest.fixture
def cell(env):
    e, tmp = env
    root, st = tmp / "oi", tmp / "oistate"
    shard = root / "shards" / SH
    shard.mkdir(parents=True)
    (shard / "litestream.env").write_text("LITESTREAM_ACCESS_KEY_ID=k1\n")
    st.mkdir()
    paths = {"restic": st / f"{SH}.restic-ok", "media": st / f"{SH}.media-ok", "drill": st / f"{SH}.drill-ok",
             "seen": st / f"{SH}.seen", "lag": tmp / "lag.seq"}
    for p in paths.values():
        p.write_text("")
        age(p, 0)
    paths["lag"].write_text("0\n")
    paths["seen"].write_text(f"{NOW}\n")
    paths["shard"] = shard
    stub = tmp / "bin" / "oi-shard-stat"
    stub.write_text(LAG_STUB)
    stub.chmod(0o755)
    e = {**e, "OI_ROOT": str(root), "OI_STATE": str(st), "NOW": str(NOW), "LS_RECHECK_S": "0",
         "OI_CELL_MODE": "1", "SLEEP_LOG": str(tmp / "sleep.log"), "OI_SHARD_STAT": str(stub),
         "LAG_SEQ": str(paths["lag"]), "LAG_LOG": str(tmp / "lag.log")}
    return e, tmp, paths


def lags(p, *vals):
    p["lag"].write_text("".join(f"{v}\n" for v in vals))


def checks(e, code=200, **extra):
    r = subprocess.run(["bash", "-c", f'. "{WATCHDOG}"; backup_age_checks {SH} {NOW}'],
                       env={**e, "STUB_HTTP_CODE": str(code), **extra},
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r


def bad_keys(tmp):
    return {f.name for f in (tmp / "state").iterdir() if f.read_text().strip() == "bad"}


def log(tmp):
    f = tmp / "watchdog.log"
    return f.read_text() if f.exists() else ""


def test_cell_all_fresh_pages_nothing(cell):
    e, tmp, _ = cell
    checks(e)
    assert bad_keys(tmp) == set()
    assert {f.name for f in (tmp / "state").iterdir()} == {
        f"litestream-lag-warn-{SH}", f"litestream-lag-crit-{SH}", f"files-warn-{SH}",
        f"files-crit-{SH}", f"media-{SH}", f"drill-age-{SH}"}
    assert log(tmp) == ""
    assert f"lag {tmp}/oi/shards/{SH} LITESTREAM_ACCESS_KEY_ID=k1" in (tmp / "lag.log").read_text()


@pytest.mark.parametrize("lag,bad", [
    (9, set()),
    (10, {"litestream-lag-warn"}),
    (59, {"litestream-lag-warn"}),
    (60, {"litestream-lag-warn", "litestream-lag-crit"}),
])
def test_litestream_lag_thresholds(cell, lag, bad):
    e, tmp, p = cell
    lags(p, lag)
    checks(e)
    assert bad_keys(tmp) == {f"{k}-{SH}" for k in bad}
    if "litestream-lag-warn" in bad:
        assert f"[warn] Shard {SH} Litestream lag over 10 s the replica lacks local LTX writes from {lag}s ago" in log(tmp)
    if "litestream-lag-crit" in bad:
        assert f"[crit] Shard {SH} Litestream lag over 60 s" in log(tmp)


def test_litestream_unreadable_replica_pages_crit(cell):
    e, tmp, p = cell
    lags(p, "fail")
    checks(e)
    assert bad_keys(tmp) == {f"litestream-lag-warn-{SH}", f"litestream-lag-crit-{SH}"}
    assert "replica position of s01 could not be read" in log(tmp)


def test_litestream_recheck_clears_first_write_after_idle(cell):
    e, tmp, p = cell
    (tmp / "bin" / "sleep").write_text(SLEEP_STUB)
    (tmp / "bin" / "sleep").chmod(0o755)
    lags(p, 3600, 0)
    checks(e, LS_RECHECK_S="2")
    assert (tmp / "sleep.log").read_text().split() == ["2"]
    assert bad_keys(tmp) == set()
    assert log(tmp) == ""


def test_litestream_no_recheck_under_warn(cell):
    e, tmp, p = cell
    (tmp / "bin" / "sleep").write_text(SLEEP_STUB)
    (tmp / "bin" / "sleep").chmod(0o755)
    lags(p, 9)
    checks(e)
    assert not (tmp / "sleep.log").exists()


@pytest.mark.parametrize("name,secs,bad", [
    ("restic", 900, set()),
    ("restic", 901, {("files-warn", "warn", "small-file backup over 15 min old")}),
    ("restic", 3600, {("files-warn", "warn", "small-file backup over 15 min old")}),
    ("restic", 3601, {("files-warn", "warn", "small-file backup over 15 min old"),
                      ("files-crit", "crit", "small-file backup over 60 min old")}),
    ("media", 10800, set()),
    ("media", 10801, {("media", "warn", "media backup over 3 h old")}),
    ("drill", 691200, set()),
    ("drill", 691201, {("drill-age", "crit", "restore drill over 8 days old")}),
])
def test_cell_age_thresholds(cell, name, secs, bad):
    e, tmp, p = cell
    age(p[name], secs)
    checks(e)
    assert bad_keys(tmp) == {f"{k}-{SH}" for k, _, _ in bad}
    for _, sev, title in bad:
        assert f"[{sev}] Shard {SH} {title}" in log(tmp)
        assert f"{SH}.{name}-ok" in log(tmp)


def test_missing_ok_files_fall_back_to_first_seen_not_shard_dir(cell):
    e, tmp, p = cell
    for k in ("restic", "media", "drill", "seen"):
        p[k].unlink()
    age(p["shard"], 0)
    checks(e)
    assert bad_keys(tmp) == set() and p["seen"].read_text().strip() == str(NOW)
    p["seen"].write_text(f"{NOW - 9 * 86400}\n")
    checks(e)
    assert bad_keys(tmp) == {f"{k}-{SH}" for k in ("files-warn", "files-crit", "media", "drill-age")}


def test_media_never_succeeded_pages_although_small_runs_touch_the_dir(cell):
    e, tmp, p = cell
    p["media"].unlink()
    p["seen"].write_text(f"{NOW - 10801}\n")
    age(p["shard"], 0)
    checks(e)
    assert bad_keys(tmp) == {f"media-{SH}"}


@pytest.mark.parametrize("mode", [None, "0"])
def test_cell_mode_off_keeps_two_hour_rule(cell, mode):
    e, tmp, p = cell
    e = {k: v for k, v in e.items() if k != "OI_CELL_MODE"}
    if mode is not None:
        e["OI_CELL_MODE"] = mode
    lags(p, 3600)
    age(p["media"], 86400)
    age(p["drill"], 30 * 86400)
    age(p["restic"], 7200)
    checks(e)
    assert {f.name for f in (tmp / "state").iterdir()} == {f"restic-{SH}"}
    assert bad_keys(tmp) == set()
    age(p["restic"], 7201)
    checks(e)
    assert bad_keys(tmp) == {f"restic-{SH}"}
    assert f"[warn] Shard {SH} file backup stale no good restic backup for 120 min (oi-backup {SH}, /var/log/oi-backup.log)." in log(tmp)


def test_age_alert_failed_delivery_retries(cell):
    e, tmp, p = cell
    age(p["media"], 10801)
    checks(e, 500)
    assert bad_keys(tmp) == set()
    checks(e, 500)
    assert bad_keys(tmp) == set()
    checks(e, 200)
    assert bad_keys(tmp) == {f"media-{SH}"}
    sent = len((tmp / "curl.log").read_text().splitlines())
    assert sent == 3
    checks(e, 200)
    assert len((tmp / "curl.log").read_text().splitlines()) == sent


def test_corrupt_backup_baseline_is_reset_and_alerted_once(cell):
    e, tmp, p = cell
    p["seen"].write_text("broken\n")
    checks(e)
    assert p["seen"].read_text().strip() == str(NOW)
    checks(e)
    assert log(tmp).count(f"[warn] Shard {SH} backup age baseline unreadable") == 1
