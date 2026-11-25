from __future__ import annotations

RUN_FACTS = ("git_sha", "git_dirty", "lock_wait_s", "load_at_start", "wire_lock_wait_s", "net_wire_stale",
             "max_threads_proc", "max_sockets_run", "source_id", "source_id_end", "env_id", "env_names", "timeout_s")


def same_knobs(have: dict, want: dict) -> dict:
    diff = {k: (have.get(k), v) for k, v in want.items() if have.get(k) != v}
    diff |= {k: (have[k], None) for k in have if k not in want and k not in RUN_FACTS}
    return diff


def run_knobs(name: str, args, params: dict, ui: bool, shards: int, fault: str | None) -> dict:
    return {"scenario": name, "scale": args.scale, "users": args.users, "seed": args.seed, "ui": ui,
            "fault": fault, **({"shards": shards} if shards > 1 else {}),
            **({"profile": True} if args.profile else {}), **({"map": True} if args.map else {}),
            **({"net": args.net} if args.net else {}), **params}


def knobs(mod, args, params: dict | None = None) -> tuple[bool, int]:
    """(ui, shards) a run of `mod` uses: UI unless --no-ui; --shards, else the scenario's
    `shards_for(params)` (a layout knob that changes the shard count), else its SHARDS, else 1."""
    n = args.shards or (mod.shards_for(params or {}) if hasattr(mod, "shards_for") else getattr(mod, "SHARDS", 1))
    return bool(getattr(mod, "UI", False)) and not args.no_ui, int(n or 1)
