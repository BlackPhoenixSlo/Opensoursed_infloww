import os
from pathlib import Path

if os.environ.get("DEMO_SHOTS_TMP") and not (os.environ.get("VAPID_KEY_FILE") or os.environ.get("VAPID_PRIVATE_KEY")):
    os.environ["VAPID_KEY_FILE"] = str(Path(os.environ["DEMO_SHOTS_TMP"]) / "vapid_private.pem")


def wire(_app, _loopback, _relay) -> None:
    pass
