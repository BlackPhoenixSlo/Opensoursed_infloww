from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from bio_pages.decide import parse_path_prefix, parse_primary_hosts
from bio_pages.files import files_dir


@dataclass(frozen=True)
class BioConfig:
    primary_hosts: frozenset[str]
    reveal_limit: float
    files_dir: Path
    flush_seconds: float
    escape_tap: bool
    path_prefix: str = ""

    @classmethod
    def from_env(cls) -> "BioConfig":
        limit = float(os.environ.get("BIO_REVEAL_LIMIT_PER_MINUTE", "60"))
        flush = float(os.environ.get("BIO_FLUSH_SECONDS", "5"))
        if limit <= 0 or flush <= 0:
            raise ValueError("invalid bio reveal limit or flush interval")
        raw_escape = os.environ.get("BIO_ESCAPE_TAP", "").strip().lower()
        if raw_escape in ("", "1", "true", "yes", "on"):
            escape_tap = True
        elif raw_escape in ("0", "false", "no", "off"):
            escape_tap = False
        else:
            raise ValueError("invalid BIO_ESCAPE_TAP")
        return cls(parse_primary_hosts(os.environ.get("BIO_PRIMARY_HOSTS", "")), limit,
                   files_dir(), flush, escape_tap, parse_path_prefix(os.environ.get("BIO_PATH_PREFIX")))
