"""service/report_recipe_decide.py — the report recipe's pure half (no DB, no
I/O): the dataset CATALOGUE, the per-dataset kind maps, `parse_recipe` (one
error per field, so a model can repair its own recipe), `resolve_window`,
`clamp_creators`, `shape` and `filename`. `report_recipe.run` executes a
parsed recipe; the help bot's Do mode renders `catalogue_text` into its
prompt (docs/plans/ultra-mode/issues/01-report-recipe.md).

A recipe names a dataset and enum keys only; code builds every query:
  {dataset, window: {preset} | {from, to}, creators?, employees?, kinds?,
   group_by?, metrics?, sort?, limit?}
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

MAX_CREATORS = 50  # stats_window.MAX_ACCOUNTS
MAX_LIMIT = 50_000  # csv_export.CSV_MAX_ROWS
JSON_MAX_ROWS = 200
HOUR_MAX_DAYS = 31  # by hour, at most 744 buckets
FORMATS = ("csv", "xlsx", "json")
TIME_UNITS = ("day", "week", "month", "hour")
PRESETS = ("today", "yesterday", "this_week", "this_month",
           "last_7_days", "last_30_days", "last_90_days", "last_365_days")
_LAST_N = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90, "last_365_days": 365}
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
FIELDS = ("dataset", "window", "creators", "employees", "kinds", "group_by", "metrics", "sort", "limit")


@dataclass(frozen=True)
class Metric:
    label: str
    unit: str  # "money" (cents in, dollars out) | "count" | "rate" (percent)
    source: tuple[str, ...]  # the cell key summed; a rate's (numerator, denominator)


@dataclass(frozen=True)
class Dataset:
    about: str
    group_by: tuple[str, ...]
    metrics: dict[str, Metric]
    kinds: tuple[str, ...]
    max_days: int
    default_group_by: tuple[str, ...]
    default_metrics: tuple[str, ...]
    employees: bool = False  # takes an `employees` restriction
    fixed_group_by: bool = False
    sql_sorted: bool = False  # sorted + cut in SQL (fan_spend): sorts by a metric only
    refuses_co_owned: bool = False  # refuses a Creator another Agency co-owns (attribution reads one Agency)


CATALOGUE: dict[str, Dataset] = {
    "sales": Dataset(
        about="Creator earnings (the Creator reports' figures, OnlyFans' own totals included)",
        group_by=("creator", "kind", "day", "week", "month"),
        metrics={"gross": Metric("Gross ($)", "money", ("gross_cents",)),
                 "net": Metric("Net ($)", "money", ("net_cents",)),
                 "net_or_80": Metric("Net or 80% ($)", "money", ("net_or_80_cents",)),
                 "fee": Metric("OF fee ($)", "money", ("fee_cents",)),
                 "sales": Metric("Sales", "count", ("sales",))},
        kinds=("ppv", "tip", "post", "subscription", "rebill", "custom"),
        max_days=400, default_group_by=("creator",), default_metrics=("gross", "net_or_80", "sales")),
    "employee_sales": Dataset(
        about="sales credited to each Employee by the Agency's attribution rules",
        group_by=("employee", "creator", "kind", "day", "week", "month"),
        metrics={"earnings": Metric("Earnings ($)", "money", ("amount_cents",)),
                 "sales": Metric("Sales", "count", ("sales",))},
        kinds=("ppv", "tip", "subscription", "other"),
        max_days=92, default_group_by=("employee",), default_metrics=("earnings", "sales"), employees=True,
        refuses_co_owned=True),
    "chat_activity": Dataset(
        about="messages Employees wrote by hand (no mass or automated sends), by send date",
        group_by=("employee", "creator", "day", "week", "month", "hour"),
        metrics={"messages": Metric("Messages", "count", ("messages",)),
                 "ppvs_sent": Metric("PPVs sent", "count", ("ppvs",)),
                 "ppvs_unlocked": Metric("PPVs unlocked", "count", ("unlocked",)),
                 "unlock_rate": Metric("Unlock rate (%)", "rate", ("unlocked", "ppvs")),
                 "chars": Metric("Characters", "count", ("chars",))},
        kinds=(),
        max_days=400, default_group_by=("employee",),
        default_metrics=("messages", "ppvs_sent", "ppvs_unlocked", "unlock_rate"), employees=True),
    "fan_spend": Dataset(
        about="each fan's spend per Creator (the Top fans ranking)",
        group_by=("creator", "fan"),
        metrics={"total": Metric("Total ($)", "money", ("total_cents",)),
                 "net_or_80": Metric("Net or 80% ($)", "money", ("net_or_80_cents",)),
                 "tips": Metric("Tips ($)", "money", ("tips_cents",)),
                 "ppv": Metric("PPV ($)", "money", ("ppv_cents",)),
                 "subs": Metric("Subscriptions ($)", "money", ("subs_cents",))},
        kinds=("ppv", "tip", "subscription", "other"),
        max_days=400, default_group_by=("creator", "fan"),
        default_metrics=("total", "net_or_80", "tips", "ppv", "subs"), fixed_group_by=True, sql_sorted=True),
}

GROUP_LABELS = {"creator": "Creator", "employee": "Employee", "kind": "Kind", "fan": "Fan",
                "day": "Day", "week": "Week of", "month": "Month", "hour": "Hour"}
KIND_LABELS = {"ppv": "PPV", "tip": "Tips", "post": "Posts", "subscription": "Subscriptions",
               "rebill": "Rebills", "custom": "Custom", "other": "Other"}
UNATTRIBUTED = "Unattributed"

# Asks the catalogue has no dataset for, and the nearest one it has.
_NEAREST = {"revenue": "sales", "earnings": "sales", "income": "sales", "creator": "sales", "model": "sales",
            "employee": "employee_sales", "chatter": "employee_sales", "commission": "employee_sales",
            "message": "chat_activity", "chat": "chat_activity", "ppv": "chat_activity", "unlock": "chat_activity",
            "fan": "fan_spend", "subscriber": "fan_spend", "spender": "fan_spend", "whale": "fan_spend",
            "churn": "fan_spend", "departed": "fan_spend", "tipper": "fan_spend"}

# Every ledger kind (attribution_backfill.REVENUE_KINDS + sales_attribution.SUBSCRIPTION_KINDS).
LEDGER_KINDS = ("ppv", "ppv_message", "ppv_post", "ppv_stream", "tip", "tip_post", "tip_stream", "custom",
                "subscription", "rebill", "referral")


def sales_kind(kind: str | None) -> str:
    """`sales`' kind of a ledger kind: `stats_per_model._kind_bucket`, the
    Creator reports' buckets (feed-post sales are `post`)."""
    if not kind:
        return "custom"
    if kind in ("ppv_post", "tip_post"):
        return "post"
    if kind.startswith("ppv"):
        return "ppv"
    if kind.startswith("tip"):
        return "tip"
    if kind in ("subscription", "rebill"):
        return kind
    return "custom"


def ledger_kind(kind: str | None) -> str:
    """`employee_sales`' and `fan_spend`'s kind of a ledger kind, as Fan
    reports bucket them (`stats_fans.fan_spend_q`: PPV_KINDS, TIP_KINDS,
    subscription + rebill); anything else is `other`."""
    if kind and kind.startswith("ppv"):
        return "ppv"
    if kind and kind.startswith("tip"):
        return "tip"
    if kind in ("subscription", "rebill"):
        return "subscription"
    return "other"


def ledger_kinds(keys: tuple[str, ...]) -> tuple[str, ...]:
    """The ledger kinds of `ledger_kind` keys, for a SQL filter."""
    return tuple(k for k in LEDGER_KINDS if ledger_kind(k) in keys)


@dataclass(frozen=True)
class Recipe:
    dataset: str
    window: tuple[str, ...]  # ("preset", name) | ("range", from, to)
    creators: tuple[str, ...] = ()
    employees: tuple[int, ...] = ()
    kinds: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    sort: str | None = None
    limit: int | None = None

    def as_dict(self) -> dict[str, Any]:
        window = ({"preset": self.window[1]} if self.window[0] == "preset"
                  else {"from": self.window[1], "to": self.window[2]})
        return {"dataset": self.dataset, "window": window, "creators": list(self.creators),
                "employees": list(self.employees), "kinds": list(self.kinds), "group_by": list(self.group_by),
                "metrics": list(self.metrics), "sort": self.sort, "limit": self.limit}


def _dedupe(xs: list[Any]) -> tuple[Any, ...]:
    return tuple(dict.fromkeys(xs))


def _str_list(v: Any) -> list[str] | None:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        return None
    return [x.strip() for x in v]


def _parse_window(v: Any) -> tuple[tuple[str, ...] | None, str | None]:
    if not isinstance(v, dict):
        return None, "give {preset} or {from, to}"
    if set(v) == {"preset"}:
        if v["preset"] in PRESETS:
            return ("preset", v["preset"]), None
        return None, "unknown preset; one of " + ", ".join(PRESETS)
    if set(v) == {"from", "to"}:
        frm, to = v["from"], v["to"]
        for d in (frm, to):
            if not isinstance(d, str) or not _DAY.fullmatch(d):
                return None, "from and to are YYYY-MM-DD dates"
            try:
                date.fromisoformat(d)
            except ValueError:
                return None, f"not a date: {d}"
        if to < frm:
            return None, "to is before from"
        return ("range", frm, to), None
    return None, "give {preset} or {from, to}"


def parse_recipe(raw: Any) -> tuple[Recipe | None, dict[str, str]]:
    """`raw` (a JSON object) as a Recipe, or None with one error per field."""
    if not isinstance(raw, dict):
        return None, {"recipe": "must be an object"}
    errors = {k: "unknown field" for k in raw if k not in FIELDS}
    name = raw.get("dataset")
    ds = CATALOGUE.get(name) if isinstance(name, str) else None
    if ds is None:
        errors["dataset"] = dataset_error(name)
        return None, errors
    window, err = _parse_window(raw.get("window"))
    if err:
        errors["window"] = err

    creators = _str_list(raw.get("creators"))
    if creators is None:
        errors["creators"] = "a list of Creator ids"
    elif len(set(creators)) > MAX_CREATORS:
        errors["creators"] = f"at most {MAX_CREATORS} Creators"

    employees: list[int] = []
    rv = raw.get("employees")
    if rv not in (None, []):
        if not ds.employees:
            errors["employees"] = f"{name} has no Employees"
        elif not isinstance(rv, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in rv):
            errors["employees"] = "a list of Employee ids"
        else:
            employees = rv

    kinds = _str_list(raw.get("kinds"))
    if kinds is None:
        errors["kinds"] = "a list of kinds"
    elif kinds and not ds.kinds:
        errors["kinds"] = f"{name} has no kinds"
    elif bad := [k for k in kinds if k not in ds.kinds]:
        errors["kinds"] = f"unknown kind {bad[0]}; one of " + ", ".join(ds.kinds)

    group_by = _str_list(raw.get("group_by"))
    if group_by is None:
        errors["group_by"] = "a list of keys"
    elif ds.fixed_group_by and group_by and tuple(dict.fromkeys(group_by)) != ds.default_group_by:
        errors["group_by"] = f"{name} is always by " + ", ".join(ds.default_group_by)
    elif bad := [g for g in group_by if g not in ds.group_by]:
        errors["group_by"] = f"unknown key {bad[0]}; one of " + ", ".join(ds.group_by)
    elif len([g for g in group_by if g in TIME_UNITS]) > 1:
        errors["group_by"] = "at most one of " + ", ".join(t for t in TIME_UNITS if t in ds.group_by)
    group_by = list(_dedupe(group_by or [])) or list(ds.default_group_by)

    metrics = _str_list(raw.get("metrics"))
    if metrics is None:
        errors["metrics"] = "a list of metrics"
    elif bad := [m for m in metrics if m not in ds.metrics]:
        errors["metrics"] = f"unknown metric {bad[0]}; one of " + ", ".join(ds.metrics)
    metrics = list(_dedupe(metrics or [])) or list(ds.default_metrics)

    sort = raw.get("sort")
    if sort is not None and (not isinstance(sort, str) or sort not in (*group_by, *metrics)):
        errors["sort"] = "one of the chosen group_by keys or metrics"
    elif ds.sql_sorted and sort is not None and sort not in metrics:
        errors["sort"] = f"{name} sorts by one of the chosen metrics"
    limit = raw.get("limit")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)
                              or not 1 <= limit <= MAX_LIMIT):
        errors["limit"] = f"a whole number from 1 to {MAX_LIMIT}"

    if errors:
        return None, errors
    return Recipe(dataset=name, window=window, creators=_dedupe(creators), employees=_dedupe(employees),
                  kinds=_dedupe(kinds), group_by=tuple(group_by), metrics=tuple(metrics),
                  sort=sort, limit=limit), {}


def dataset_error(name: Any) -> str:
    """The refusal for a dataset the catalogue lacks: the nearest one, and the list."""
    return f"not available; nearest is {nearest_dataset(str(name or ''))}; one of " + ", ".join(sorted(CATALOGUE))


def nearest_dataset(ask: str) -> str:
    """The catalogue's nearest dataset to an ask it has no dataset for."""
    low = ask.lower()
    for word, ds in _NEAREST.items():
        if word in low:
            return ds
    close = difflib.get_close_matches(low, sorted(CATALOGUE), n=1, cutoff=0.5)
    return close[0] if close else "sales"


def time_unit(group_by: tuple[str, ...]) -> str | None:
    return next((g for g in group_by if g in TIME_UNITS), None)


def sort_key(recipe: Recipe) -> str:
    """The key a report is ordered by: `sort`, else the time key, else the
    first metric. The one source for `shape` and fan_spend's SQL ORDER BY
    (whose `parse_recipe` admits a metric only)."""
    return recipe.sort or time_unit(recipe.group_by) or recipe.metrics[0]


def order_label(recipe: Recipe) -> str:
    """`sort_key` in plain words for the plan card: a metric high to low, a key A to Z."""
    key = sort_key(recipe)
    ds = CATALOGUE[recipe.dataset]
    if key in recipe.metrics:
        return f"{ds.metrics[key].label}, high to low"
    return f"{GROUP_LABELS[key]}, {'oldest first' if key in TIME_UNITS else 'A to Z'}"


def week_start_of(day: date, week_start: str) -> date:
    return day - timedelta(days=(day.weekday() + (1 if week_start == "sunday" else 0)) % 7)


def resolve_window(recipe: Recipe, today: date, week_start: str = "monday") -> tuple[tuple[date, date] | None, str | None]:
    """The recipe's window as local [from, to] days (presets as
    app/lib/dateRange.ts: "last N days" ends today), or its refusal: over the
    dataset's cap, or by hour over HOUR_MAX_DAYS."""
    if recipe.window[0] == "preset":
        p = recipe.window[1]
        if p == "today":
            frm = to = today
        elif p == "yesterday":
            frm = to = today - timedelta(days=1)
        elif p == "this_week":
            frm = week_start_of(today, week_start)
            to = frm + timedelta(days=6)
        elif p == "this_month":
            frm = today.replace(day=1)
            to = (frm.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        else:
            frm, to = today - timedelta(days=_LAST_N[p] - 1), today
    else:
        frm, to = date.fromisoformat(recipe.window[1]), date.fromisoformat(recipe.window[2])
    days = (to - frm).days + 1
    cap = CATALOGUE[recipe.dataset].max_days
    if days > cap:
        return None, f"the window is {days} days; {recipe.dataset} takes at most {cap}"
    if time_unit(recipe.group_by) == "hour" and days > HOUR_MAX_DAYS:
        return None, f"by hour takes at most {HOUR_MAX_DAYS} days; the window is {days}"
    return (frm, to), None


def today_in(zone: ZoneInfo | None, now: datetime) -> date:
    """The local day of naive UTC `now` in `zone` (UTC when None)."""
    at = now.replace(tzinfo=timezone.utc)
    return (at.astimezone(zone) if zone else at).date()


def clamp_creators(named: tuple[str, ...], owned: set[str], *, co_owned: set[str] | frozenset = frozenset(),
                   refuse_co_owned: bool = False) -> tuple[list[str] | None, str | None]:
    """The Creators a run reads: the named ones when all are the Agency's
    (`owned`), else every owned one; refused for a foreign Creator, more than
    MAX_CREATORS, or (`refuse_co_owned`) one another Agency co-owns. Empty
    when the Agency owns none: the caller then reads nothing."""
    if foreign := [c for c in named if c not in owned]:
        return None, f"not one of your Creators: {foreign[0]}"
    ids = sorted(set(named)) if named else sorted(owned)
    if len(ids) > MAX_CREATORS:
        return None, f"at most {MAX_CREATORS} Creators; name some"
    if refuse_co_owned and (shared := [c for c in ids if c in co_owned]):
        return None, f"Creator {shared[0]} is shared with another Agency; employee_sales cannot read it yet"
    return ids, None


def period_label(day: str, unit: str, week_start: str = "monday") -> str:
    """A local 'YYYY-MM-DD' day's label by `unit` (day, week = its week's
    first day, month = 'YYYY-MM')."""
    if unit == "week":
        return week_start_of(date.fromisoformat(day), week_start).isoformat()
    if unit == "month":
        return day[:7]
    return day


def edge_label(edge: datetime, zone: ZoneInfo | None, unit: str) -> str:
    """A bucket's label from its naive UTC start (`stats_window.bucket_edges`)."""
    at = edge.replace(tzinfo=timezone.utc)
    local = at.astimezone(zone) if zone else at
    return local.strftime({"month": "%Y-%m", "hour": "%Y-%m-%d %H:00"}.get(unit, "%Y-%m-%d"))


def columns(recipe: Recipe) -> list[str]:
    ds = CATALOGUE[recipe.dataset]
    return [GROUP_LABELS[g] for g in recipe.group_by] + [ds.metrics[m].label for m in recipe.metrics]


def _label(dim: str, key: Any, names: dict[str, dict[Any, str]]) -> str:
    if dim == "kind":
        return KIND_LABELS.get(key, str(key))
    if dim == "employee" and key is None:
        return names.get("employee", {}).get(None, UNATTRIBUTED)
    return names.get(dim, {}).get(key, "" if key is None else str(key))


def _value(m: Metric, sums: dict[str, int]) -> float | int | None:
    if m.unit == "rate":
        num, den = (sums.get(k, 0) for k in m.source)
        return round(num * 100 / den, 1) if den else None
    v = sums.get(m.source[0], 0)
    return round(v / 100, 2) if m.unit == "money" else v


def shape(recipe: Recipe, cells: list[dict[str, Any]],
          names: dict[str, dict[Any, str]] | None = None) -> tuple[list[str], list[list[Any]]]:
    """The table of `cells` (dicts of the group_by keys and the metrics'
    source sums, in cents): summed per the recipe's group_by, a rate after
    summing (none with no denominator), money in dollars, sorted (a metric
    high to low, a key A to Z; by default the time key, else the first
    metric) and cut to `limit`. Labels from `names` {dim: {key: label}}."""
    ds = CATALOGUE[recipe.dataset]
    names = names or {}
    sources = {s for m in recipe.metrics for s in ds.metrics[m].source}
    groups: dict[tuple, dict[str, int]] = {}
    for c in cells:
        acc = groups.setdefault(tuple(c.get(g) for g in recipe.group_by), dict.fromkeys(sources, 0))
        for s in sources:
            acc[s] += int(c.get(s) or 0)
    rows = [([_label(g, k, names) for g, k in zip(recipe.group_by, key)],
             [_value(ds.metrics[m], sums) for m in recipe.metrics]) for key, sums in groups.items()]
    rows.sort(key=lambda r: [x.lower() for x in r[0]])

    def by(field: str) -> None:
        if field in recipe.group_by:
            i = recipe.group_by.index(field)
            rows.sort(key=lambda r: r[0][i].lower())
        else:
            i = recipe.metrics.index(field)
            rows.sort(key=lambda r: (r[1][i] is None, -(r[1][i] or 0)))

    sort = sort_key(recipe)
    if sort != recipe.metrics[0] and not recipe.sort:
        by(recipe.metrics[0])
    by(sort)
    if recipe.limit is not None:
        rows = rows[:recipe.limit]
    return columns(recipe), [labels + values for labels, values in rows]


def filename(dataset: str, frm: date | str, to: date | str, fmt: str) -> str:
    return f"{dataset.replace('_', '-')}_{frm}_to_{to}.{fmt}"


def catalogue_text() -> str:
    """The catalogue as prompt text, sorted, no account data: byte-stable."""
    lines = []
    for name in sorted(CATALOGUE):
        ds = CATALOGUE[name]
        group = (", ".join(ds.group_by) + " (fixed)") if ds.fixed_group_by else ", ".join(sorted(ds.group_by))
        lines.append(f"- {name}: {ds.about}. group_by: {group}. metrics: {', '.join(sorted(ds.metrics))}. "
                     f"kinds: {', '.join(sorted(ds.kinds)) or '(none)'}. "
                     f"employees: {'yes' if ds.employees else 'no'}. longest window: {ds.max_days} days.")
    return "\n".join(lines)


def catalogue_json() -> dict[str, Any]:
    """The catalogue for GET /admin/reports/catalogue."""
    return {"datasets": [
        {"dataset": name, "about": ds.about, "group_by": list(ds.group_by), "fixed_group_by": ds.fixed_group_by,
         "metrics": [{"metric": k, "label": m.label, "unit": m.unit} for k, m in ds.metrics.items()],
         "kinds": list(ds.kinds), "employees": ds.employees, "max_days": ds.max_days,
         "default_group_by": list(ds.default_group_by), "default_metrics": list(ds.default_metrics)}
        for name, ds in sorted(CATALOGUE.items())],
        "presets": list(PRESETS), "formats": list(FORMATS), "max_creators": MAX_CREATORS,
        "hour_max_days": HOUR_MAX_DAYS}
