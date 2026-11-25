from __future__ import annotations

CLICKS = ("tracking links: every /t/ click sent is stored once per link (tracking_clicks rows, click_count "
          "and the list route all == seeded + the 302s answered)")
REDIRECT = "tracking links: every /t/<slug> answer is a 302 to that link's own target"
BY_DAY = ("tracking links: each link's 30-day analytics series == its seeded clicks per New York day (the report "
          "zone) + the storm's 302s on theirs, and its total == their sum")
EARNINGS = ("OF tracking links: every link of each Creator listed, per link earnings (gross and net), fans counted "
            "and fans who spent == the oracle (latest claiming link opened at or before each sale, still open, "
            "cleared / pending only; each of those branches seeded), and each link's /fans rows sum to it")
CLAIMERS = ("OF tracking links: claimers single-flight: one claimers walk per link with subscribers (every page "
            "once) under concurrent owners and across a recompute, none for a zero-subscriber or created link")
CREATED = "OF tracking links: the Create dialog's POST answers 200 with OF's new link, for every Creator"
GATE_PAGE = ("tracking links: every GET of a bot-checked link answers 200 with the Turnstile page: no Location, "
             "its target nowhere in the body, Cache-Control no-store")
GATE_VERIFY = ("tracking links: every bot-check verify with a passing token answers 200 {url: that link's own "
               "target}, every failing one 403 with no url, and Cloudflare's siteverify got exactly one call per "
               "verify, with the relay's secret and the fan's address")
GATE_THROTTLE = ("tracking links: one fresh address posting VERIFY_CAPACITY + 3 failing bot-check verifies to a "
                 "gated link gets 403 for the first VERIFY_CAPACITY and 429 with Retry-After for exactly the last 3; "
                 "siteverify got VERIFY_CAPACITY calls (none for a 429) and the link counted no click")
GATE_COUNT = ("tracking links: a bot-checked link's clicks (tracking_clicks rows, click_count, the list) == the "
              "verifies that passed, exactly; its GETs and failed verifies count none")
GATE_CREATE = ("tracking links: every Create with a scheme-less target stores it as https://<it>, and bot_check "
               "(set at create, or by PATCH) reads back on the list")
UI_VIEWED = ("UI: an open Growth > Tracking links page refetches its OF links and their earnings once its hour "
             "(GROWTH_VIEWED_REFRESH_MS) is up, not before, and the relay reads OF's /campaigns again")
STATS_SUMMARY = ("tracking links: each Creator's summary (clicks today / 7 / 30 days, every link's 7-day sparkline, "
                 "the top link) == the seed + the storm's 302s + the plan's passed verifies, per New York day")
STATS_BREAKDOWN = ("tracking links: each ungated link's 30-day Opened in / Came from / Country == the hand labels of "
                   "its seeded and storm clicks exactly (a spoofed CF-IPCountry filed XX), each summing to its total")
STATS_INVARIANT = ("tracking links: per link analytics buckets == raw rows == click_count")
CLIENT_IP = ("tracking links: behind a CDN (EDGE_PROXIES=cloudflare), every click the storm stored holds the fan's "
             "own address (its CF-Connecting-IP), never the Cloudflare server's or the proxy's")


def _click_lost_1_in_20() -> None:
    from collections import Counter

    import tracking_links_api as tla

    real = tla.update
    writes: Counter = Counter()

    def lossy(*a, **k):
        statement = real(*a, **k)

        class ClickUpdate:
            def where(self, condition):
                self.link_id = condition.right.value
                self.statement = statement.where(condition)
                return self

            def values(self, **values):
                writes[self.link_id] += 1
                if writes[self.link_id] == 1 or writes[self.link_id] % 20 == 0:
                    raise RuntimeError("slop fault: click write lost")
                return self.statement.values(**values)

        return ClickUpdate()

    tla.update = lossy


def _classify_raises() -> None:
    import click_classify

    def boom(*_args):
        raise RuntimeError("slop fault: classifier failed")

    click_classify.classify = boom


def _claimers_no_memo() -> None:
    import of_tracking_api as ota

    real = ota._claimers_cached

    def no_memo(client, account_id, c):
        ota._CLAIMERS_CACHE.pop((account_id, ota.safe_int(c.get("id"))), None)
        return real(client, account_id, c)

    ota._claimers_cached = no_memo


def _spend_first_link() -> None:
    import inspect
    import textwrap

    import of_tracking_api as ota

    src = textwrap.dedent(inspect.getsource(ota._spend))
    old = "lst.sort(reverse=True)"
    if src.count(old) != 1:
        raise SystemExit("slop: of-tracking-spend-first-link: of_tracking_api._spend's sort changed")
    ns: dict = {}
    exec(compile(src.replace(old, "lst.sort()"), ota.__file__, "exec"), ota.__dict__, ns)
    ota._spend = ns["_spend"]


def _cdn_header_ignored() -> None:
    import client_addr

    client_addr.EDGE_PROXIES = ()


def _stats_utc_days() -> None:
    async def utc(_account_id):
        return None

    import stats
    stats._report_zone = utc


def _bot_check_fails_open() -> None:
    import turnstile

    async def always(_secret, _token, _ip):
        return True

    turnstile.passes = always


def _verify_unthrottled() -> None:
    import tracking_links_api as tla

    tla._verify_wait = lambda _request: None


def register(Fault) -> dict:
    return {
        "tracking-click-lost-1-in-20": Fault(_click_lost_1_in_20, (CLICKS, BY_DAY, STATS_SUMMARY, STATS_BREAKDOWN, GATE_COUNT)),
        "tracking-classify-raises": Fault(_classify_raises, (STATS_BREAKDOWN,)),
        "of-tracking-claimers-no-memo": Fault(_claimers_no_memo, (CLAIMERS,)),
        "of-tracking-spend-first-link": Fault(_spend_first_link, (EARNINGS,)),
        "client-addr-cdn-header-ignored": Fault(_cdn_header_ignored, (CLIENT_IP, STATS_BREAKDOWN)),
        "tracking-bot-check-fails-open": Fault(_bot_check_fails_open,
                                               (GATE_VERIFY, GATE_COUNT, STATS_SUMMARY, GATE_THROTTLE)),
        "tracking-stats-utc-days": Fault(_stats_utc_days, (BY_DAY, STATS_SUMMARY)),
        "tracking-verify-unthrottled": Fault(_verify_unthrottled, (GATE_THROTTLE,)),
        "growth-viewed-no-refetch": Fault(None, (UI_VIEWED,), browser=(
            (r"refetchInterval:\s*GROWTH_VIEWED_REFRESH_MS", "refetchInterval: false"),)),
    }
