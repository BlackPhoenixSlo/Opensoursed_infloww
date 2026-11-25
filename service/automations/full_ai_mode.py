MODES = ("test", "shadow", "live")


def full(mode: str | None) -> bool:
    return mode in ("test", "live")
