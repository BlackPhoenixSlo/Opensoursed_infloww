from __future__ import annotations

PPV_SEND_BODY = ("Composer PPV send: vault media + price + lock + 2 GIFs → one send with the first GIF, the trailing "
                 "GIF only after uploads settle")


def register(Fault) -> dict:
    return {
        "trailing-gif-before-upload": Fault(None, (PPV_SEND_BODY,), browser=(
            (r"if \(args\.uploads && sent\)", "if (false)"),
        )),
    }
