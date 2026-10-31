"""The chat Composer's send (app/components/chat/Composer.tsx `submit`, its pure parts in composerSubmit.ts)
break-it-once fault: lib/faults.py merges `register(Fault)` into FAULTS. Client side: actors/ui.py rewrites the
JS `next dev` serves, never the repo files. The check lives here and scenarios/2026-10-29-state-reducers.py
(section 18c, `_chat_ppv`) imports it, so the target can never name a check that does not exist.
"""
from __future__ import annotations

PPV_SEND_BODY = ("Composer PPV send: vault media + price + lock + 2 GIFs → one send with the first GIF, the trailing "
                 "GIF only after uploads settle")


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-29-state-reducers --break --fault=trailing-gif-before-upload
        # Composer.tsx `submit`: the trailing GIFs stop waiting on the send's `settled` when it still waits on its
        # uploads, so the GIF-only send reaches OF before the message it trails (whose upload is still running).
        # Only the PPV send check goes red. Composer.tsx is served in Messages Pro's page chunk only (1 file, as
        # `refused-schedule-lost-on-switch` measures).
        "trailing-gif-before-upload": Fault(None, (PPV_SEND_BODY,), browser=(
            (r"if \(args\.uploads && sent\)", "if (false)"),
        )),
    }
