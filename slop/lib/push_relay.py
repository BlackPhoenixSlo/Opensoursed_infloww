"""Web Push's part of the slop relay (lib/relay.py loads it before the product): keeps the VAPID key
in the run's temp dir. push_send.vapid() writes a missing key to VAPID_KEY_FILE, default
service/secrets/vapid_private.pem in the repo; so every slop relay gets
VAPID_KEY_FILE=$DEMO_SHOTS_TMP/vapid_private.pem unless the scenario set VAPID_KEY_FILE or
VAPID_PRIVATE_KEY. Same file across a relay restart (start_relay keeps DEMO_SHOTS_TMP), so a restart
keeps the key, as in prod. Push itself stays off unless the scenario's RELAY_ENV sets VAPID_SUBJECT
(scenarios/2026-11-03-os-ping-push.py). No hooks.
"""

import os
from pathlib import Path

if os.environ.get("DEMO_SHOTS_TMP") and not (os.environ.get("VAPID_KEY_FILE") or os.environ.get("VAPID_PRIVATE_KEY")):
    os.environ["VAPID_KEY_FILE"] = str(Path(os.environ["DEMO_SHOTS_TMP"]) / "vapid_private.pem")


def wire(_app, _loopback, _relay) -> None:
    pass
