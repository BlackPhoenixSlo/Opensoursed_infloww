#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402  (first: temp DB)

import accounts  # noqa: E402
import events  # noqa: E402

A, B, C, W = "9401", "9402", "9403", "9409"


def case_app_tab_mark():
    assert events.is_app_tab("1", None) is True, "the app's marked stream"
    assert events.is_app_tab(None, "https://app.example/inbox") is True, "an unmarked browser page"
    assert events.is_app_tab("1", "https://app.example/inbox") is True
    assert events.is_app_tab(None, None) is False, "the desktop notifier: unmarked, no Referer"
    assert events.is_app_tab(None, "") is False


async def case_union_of_tab_clamps_minus_watchers():
    orig = accounts.is_watcher
    accounts.is_watcher = lambda aid: aid == W
    qs = []
    try:
        qs.append(await events.subscribe("all", accounts=frozenset({A, W}), tab=True))
        qs.append(await events.subscribe(f"model:{B}", accounts=frozenset({B}), tab=True))
        qs.append(await events.subscribe("all", accounts=frozenset({B}), tab=True))
        qs.append(await events.subscribe("all", accounts=None, tab=True))
        qs.append(await events.subscribe("all", accounts=frozenset({C})))
        assert events.open_tab_accounts() == frozenset({A, B}), events.open_tab_accounts()
        for q in qs:
            await events.unsubscribe("all", q)
        assert events.open_tab_accounts() == frozenset(), "empty after the last tab unsubscribes"
    finally:
        accounts.is_watcher = orig
        for q in qs:
            await events.unsubscribe("all", q)


_harness.run()
