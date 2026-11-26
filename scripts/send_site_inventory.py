from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from functools import cache
from typing import NamedTuple

SERVICE = Path(__file__).resolve().parents[1] / "service"
PRIMITIVES = frozenset({
    "send_message", "post_message", "schedule_message", "send_mass_message",
    "schedule_mass_message", "publish_schedule", "send_mass_run", "catchup_queue",
    "send_dropping_bad_media", "send_dropping_bad_media_sync", "materialize_via_message",
    "of_send_or_schedule_mass", "_send_or_schedule_mass", "send_priced",
})


class SendInventory(NamedTuple):
    calls: Counter
    modules: frozenset[str]
    endpoints: frozenset[tuple[str, str]]

    def route_labels(self, route_facts: dict[str, dict]) -> frozenset[str]:
        return frozenset(f"http:{route}" for route, facts in route_facts.items()
                         if facts.get("kind") == "api" and (facts.get("file"), facts.get("func")) in self.endpoints)


class _Sites(ast.NodeVisitor):
    def __init__(self, module: str, calls: Counter, aliases: dict[str, str]):
        self.module, self.calls, self.aliases = module, calls, aliases
        self.functions: list[str] = []

    def visit_FunctionDef(self, node):
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def record(self, name):
        if name in PRIMITIVES:
            self.calls[f"{self.module}:{'.'.join(self.functions)}:{name}"] += 1

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            self.record(self.aliases.get(node.func.id, node.func.id))
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load):
            self.record(node.attr)
        self.generic_visit(node)


def scan(module: str, source: str | bytes, calls: Counter) -> None:
    tree = ast.parse(source, filename=module)
    aliases = {a.asname: a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               for a in node.names if a.asname and a.name in PRIMITIVES}
    _Sites(module, calls, aliases).visit(tree)


@cache
def inventory() -> SendInventory:
    calls: Counter = Counter()
    for file in sorted(SERVICE.rglob("*.py")):
        rel = file.relative_to(SERVICE)
        if "tests" not in rel.parts and not any(part.startswith(".") for part in rel.parts):
            scan(rel.as_posix(), file.read_bytes(), calls)
    endpoints = frozenset((module, qualname.split(".", 1)[0])
                          for module, qualname, _ in (key.split(":") for key in calls))
    return SendInventory(calls, frozenset(module for module, _ in endpoints), endpoints)
