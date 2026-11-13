"""service/assistant_report.py — do-mode's `report_export`: a report file of the Agency's numbers.

Ultra-mode ticket 02 (docs/plans/ultra-mode/issues/02-do-mode-export.md). The
model names a dataset from `report_recipe_decide.CATALOGUE` and the Creators /
Employees in the request's words; everything else is here:

  • `report_ctx` — an owner's context (Creators, Employees, report zone, week
    start, today, co-owned Creators) from `report_recipe.agency_scope`, the
    read `/admin/reports/run` makes; None for anyone else (no export).
  • `resolve_export` — pure: each name resolves uniquely (`resolve_name`) or
    is `unresolved` (the slots then carry no recipe: Download stays off); the
    window is fixed to dates; a restriction that does not parse, or a key the
    schema does not have, refuses — never a wider report. Only sort / limit
    are dropped, with a line why.
  • `report_lines` — the user block's CREATORS / EMPLOYEES / TODAY lines.

assistant_draft keeps REPORT_FLOW, the veto and the one dispatch in `interpret`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Iterable

import report_recipe_decide as rd
from auth import get_request_user
from db.engine import get_session
from report_recipe import agency_scope

# A file / report word in the languages we see. No such word = no export (assistant_draft.vetoed).
REPORT_WORD = re.compile(r"\b(export\w*|report\w*|download\w*|csv|excel|xlsx|spreadsheets?|sheets?|files?|"
                          r"tables?|breakdown|stats|statistics?|numbers|figures|data|"
                          r"inform[ea]s?|reporte?s?|exporta\w*|descarga\w*|rapports?|berichte?|tabell\w*|"
                          r"poro[čc]il\w*|izvoz\w*|izvozi\w*|relat[óo]rios?|planilha\w*|hoja de c[áa]lculo)\b", re.I)
_XLSX_WORD = re.compile(r"\b(excel|xlsx|spreadsheets?|hoja de c[áa]lculo|planilha\w*|tabellenkalkulation)\b", re.I)

# Owners only, like /admin/reports/run.
EXPORT_NOT_ALLOWED_ANSWER = "Only the Agency owner can export reports — ask them to run it."
NO_REPORT_ANSWER = "I couldn't tell which report you want — say what to export, e.g. \"last month's sales per Creator\"."
REPORT_DEFAULT_PRESET = "last_30_days"
WHEN_NOTE = "Last 30 days — you didn't say when."
_NAME_LIST_MAX = 200          # names per CREATORS / EMPLOYEES line
_RAW_KEYS = (*rd.FIELDS, "format")


@dataclass(frozen=True)
class ReportCtx:
    """What an owner's export draft resolves against: the Agency's Creators
    (id, nickname), its Employees (id, name), its report zone + week start,
    today there, and the Creators another Agency co-owns (`shared`). A pure
    projection of `report_recipe.AgencyScope` (`report_ctx`): name-sorted
    tuples (the prompt's lines are stable), the zone as its key, no ZoneInfo /
    DB — tests and the eval seam build it from literals."""
    creators: tuple[tuple[str, str], ...]
    employees: tuple[tuple[int, str], ...]
    zone: str
    today: date
    week_start: str
    shared: frozenset[str]


@dataclass
class ExportDraft:
    """`resolve_export`'s draft; assistant_draft wraps it in its `Draft` (that
    module imports this one, so the reverse import would be a cycle)."""
    slots: dict[str, Any]
    assumptions: list[str]
    unresolved: list[str]


async def report_ctx() -> ReportCtx | None:
    """The signed-in owner's ReportCtx (`report_recipe.agency_scope`); None for
    a chatter or no session: no export (`/admin/reports/run` re-checks)."""
    user = get_request_user()
    if user is None:
        return None
    async with get_session() as s:
        sc = await agency_scope(s, user.id, datetime.utcnow())
    return ReportCtx(
        creators=tuple(sorted(sc.nicknames.items(), key=lambda x: (x[1].lower(), x[0]))),
        employees=tuple(sorted(sc.employees.items(), key=lambda x: (x[1].lower(), x[0]))),
        zone=sc.zone.key if sc.zone else "UTC", today=sc.today, week_start=sc.week_start, shared=sc.co_owned)


def report_lines(ctx: ReportCtx) -> list[str]:
    """The user block's lines for an owner: the names the request resolves against, and today."""
    out = []
    for label, opts in (("CREATORS", ctx.creators), ("EMPLOYEES", ctx.employees)):
        shown = sorted({nm for _, nm in opts}, key=str.lower)[:_NAME_LIST_MAX]
        out.append(f"{label}: " + (", ".join(shown) or "(none)"))
    out.append(f"TODAY: {ctx.today.isoformat()} ({ctx.zone})")
    return out


def name_key(s: str) -> str:
    """A name as compared: casefolded, accents off, letters and digits of any script ("Žan" → "zan", "李" → "李")."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", (s or "").casefold())
                   if not unicodedata.combining(ch) and ch.isalnum())


def resolve_name(want: str, options: Iterable[tuple[Any, str]], what: str) -> tuple[Any, str | None]:
    """(key, None) when `want` names exactly one option — an exact match
    (name or key, `name_key`), else the single option it contains (`want` of 2+
    characters) or is contained in (an option of 3+); else (None, the
    unresolved sentence). Two candidates or only a close spelling never
    resolve: a wrong Creator in a file is worse than a question."""
    n = name_key(want)
    opts = [(k, nm) for k, nm in options]
    if not n:
        return None, f'Which {what} is "{want}"?'
    exact = [(k, nm) for k, nm in opts if name_key(nm) == n or name_key(str(k)) == n]
    if len(exact) == 1:
        return exact[0][0], None
    part = exact or [(k, nm) for k, nm in opts
                     if (m := name_key(nm)) and ((len(n) >= 2 and n in m) or (len(m) >= 3 and m in n))]
    if len(part) == 1:
        return part[0][0], None
    if not part:
        return None, f'No {what} called "{want}" — name one of yours.'
    return None, f'"{want}" could be {" or ".join(nm for _, nm in part[:3])} — say which {what}.'


def _widened(want: str, key: Any, options: list[tuple[Any, str]], what: str, request: str) -> str | None:
    """The model wrote a name the request does not hold ("Mia Rose" for "Mia",
    "Li Rose" for "Li"): the request's longest word inside it must resolve to
    the same option, else the question that word raises. A one-character word
    ("李") counts only as a whole word of an option's name; one that is none is
    no name. None when the request holds the name."""
    if not request or name_key(want) in name_key(request):
        return None
    nm = dict(options)
    for word in sorted(re.findall(r"\w+", request), key=lambda w: -len(name_key(w))):
        k = name_key(word)
        if not k or k not in name_key(want):
            continue
        if len(k) >= 2:
            got, problem = resolve_name(word, options, what)
            if problem:
                return problem
        else:
            hits = [o for o, n in options if k in {name_key(x) for x in re.findall(r"\w+", n)}]
            if not hits:
                continue
            if len(hits) > 1:
                return f'"{word}" could be {" or ".join(nm[o] for o in hits[:3])} — say which {what}.'
            got = hits[0]
        if got != key:
            return f'"{word}" could be {nm[got]} or {nm[key]} — say which {what}.'
        return None
    return None


_LIST_SEP = re.compile(r"[,;/&+|()\n]")


def _spans(request: str) -> list[tuple[str, frozenset[int]]]:
    """The request per list item ("Mia, Rose" is two): its `name_key` text and
    the positions a name may start / end at — word edges, and each character of
    a script written without spaces ("导出李明的销售")."""
    out = []
    for item in _LIST_SEP.split(request):
        keys: list[str] = []
        for word in re.findall(r"\w+", item):
            run = ""
            for ch in word:
                if unicodedata.category(ch) == "Lo":
                    keys += [name_key(run), name_key(ch)]
                    run = ""
                else:
                    run += ch
            keys.append(name_key(run))
        edges, at = {0}, 0
        for k in keys:
            at += len(k)
            edges.add(at)
        out.append(("".join(keys), frozenset(edges)))
    return out


def _hits(k: str, spans: list[tuple[str, frozenset[int]]]) -> list[tuple[int, int, int]]:
    """Where the request names `k` (a `name_key`): (list item, start, end), whole words only."""
    return [(i, s, s + len(k)) for i, (text, edges) in enumerate(spans) for s in edges
            if k and text.startswith(k, s) and s + len(k) in edges]


def _longest(want: str, key: Any, options: list[tuple[Any, str]], what: str, request: str) -> tuple[Any, str | None]:
    """The option the request names over the model's pick: "Mia" for "export
    Mia Rose's sales" (Creators Mia and Mia Rose) → Mia Rose. The pick stands
    when the request names it outside every longer option's name, or not at
    all (`_widened` judges that); else the longest option over it, and two
    such options are a question — never the shorter name silently."""
    nm = dict(options)
    spans = _spans(request or "")
    k = name_key(nm[key])
    longer = {o: _hits(m, spans) for o, n in options if len(m := name_key(n)) > len(k) and k in m}
    over: set[Any] = set()
    for i, s, e in _hits(k, spans):
        cover = [o for o, hits in longer.items() if any(j == i and a <= s and e <= b for j, a, b in hits)]
        if not cover:
            return key, None
        over.update(cover)
    if not over:
        return key, None
    keys = {o: name_key(nm[o]) for o in over}
    top = sorted((o for o in over if not any(keys[o] != keys[p] and keys[o] in keys[p] for p in over)),
                 key=lambda o: nm[o].lower())
    if len(top) == 1:
        return top[0], None
    return None, f'"{want}" could be {" or ".join(nm[o] for o in [key, *top][:3])} — say which {what}.'


def _report_kind(dataset: rd.Dataset, k: Any) -> Any:
    """A kind as the model may write it ("Tips", "PPVs") → the dataset's key; else as given (the parse refuses it)."""
    n = name_key(str(k))
    for key in dataset.kinds:
        if n in (key, name_key(rd.KIND_LABELS.get(key, "")), key + "s"):
            return key
    return k


def _report_refusal(field_: str, reason: str) -> str:
    return f"I can't make that report — {field_}: {reason}."


def resolve_export(raw: Any, ctx: ReportCtx, *, request: str = "", assumptions: Iterable[str] = (),
                   unresolved: Iterable[str] = ()) -> tuple[ExportDraft | None, str | None]:
    """The model's `report` → the export's slots, or (None, the refusal).
    `assumptions` / `unresolved`: the model's own lines, cleaned. Names resolve
    uniquely; one that does not is `unresolved` and the slots carry no recipe
    (Download stays off). No Creator named = all of the Agency's. A key the
    schema lacks, or a restriction that does not parse (dataset, window,
    creators, employees, kinds, group_by, metrics), refuses — never a wider
    report; absent / null is the default. Only sort / limit are dropped, with
    a line why. The window is fixed to dates here."""
    if not isinstance(raw, dict):
        return None, NO_REPORT_ANSWER
    if extra := [k for k in raw if k not in _RAW_KEYS]:
        return None, _report_refusal(extra[0], "unknown field")
    name = raw.get("dataset")
    name = name.strip() if isinstance(name, str) else name
    ds = rd.CATALOGUE.get(name) if isinstance(name, str) else None
    if ds is None:
        return None, _report_refusal("dataset", rd.dataset_error(name))
    notes: list[str] = []
    problems: list[str] = []

    def names(key: str, options: list, what: str) -> tuple[list, list[str]] | None:
        got = raw.get(key)
        if got is None:
            return [], []
        if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
            return None
        ids, shown = [], []
        for want in got:
            k, problem = resolve_name(want, options, what)
            problem = problem or _widened(want, k, options, what, request)
            if not problem:
                k, problem = _longest(want, k, options, what, request)
            if problem:
                problems.append(problem)
            elif k not in ids:
                ids.append(k)
                shown.append(dict(options)[k])
        return ids, shown

    creators, employees = list(ctx.creators), list(ctx.employees)
    got_c = names("creators", creators, "Creator")
    if got_c is None:
        return None, _report_refusal("creators", "a list of Creator names")
    if raw.get("employees") not in (None, []) and not ds.employees:
        return None, _report_refusal("employees", f"{name} has no Employees")
    got_e = names("employees", employees, "Employee")
    if got_e is None:
        return None, _report_refusal("employees", "a list of Employee names")
    (creator_ids, creator_names), (employee_ids, employee_names) = got_c, got_e
    window = raw.get("window")
    if isinstance(window, str):
        window = {"preset": window}
    if window is None:
        window = {"preset": REPORT_DEFAULT_PRESET}
        notes.append(WHEN_NOTE)
    kinds = raw.get("kinds")
    rec: dict[str, Any] = {"dataset": name, "window": window, "creators": creator_ids, "employees": employee_ids,
                           "kinds": ([_report_kind(ds, k) for k in kinds] if isinstance(kinds, list)
                                     else [] if kinds is None else kinds)}
    for key in ("group_by", "metrics", "sort", "limit"):
        if raw.get(key) is not None:
            rec[key] = raw[key]
    recipe, errors = rd.parse_recipe(rec)
    dropped = [k for k in ("sort", "limit") if k in errors]
    for key, line in (("sort", "Sorted the usual way — couldn't sort by {v}."),
                      ("limit", "Every row — {v} is not a row count.")):
        if key in dropped:
            notes.append(line.format(v=json.dumps(rec.pop(key), ensure_ascii=False)))
            errors.pop(key)
    if errors:
        key = next(iter(errors))
        return None, _report_refusal(key, errors[key])
    if dropped:
        recipe, _ = rd.parse_recipe(rec)
    assert recipe is not None
    days, err = rd.resolve_window(recipe, ctx.today, ctx.week_start)
    if days is None:
        return None, _report_refusal("window", err)
    frm, to = days
    recipe = replace(recipe, window=("range", frm.isoformat(), to.isoformat()))
    if not creators:
        problems.append("You have no Creators connected yet — nothing to export.")
    elif not raw.get("creators") and len(creators) > rd.MAX_CREATORS:
        problems.append(f"You have {len(creators)} Creators; a report takes at most {rd.MAX_CREATORS} — "
                        "name the ones you want.")
    if ds.refuses_co_owned and (shared := [nm for k, nm in creators
                                           if k in ctx.shared and (not creator_ids or k in creator_ids)]):
        problems.append(f"{', '.join(shared[:3])} {'is' if len(shared) == 1 else 'are'} shared with another "
                        f"Agency — {name.replace('_', ' ')} can't read {'it' if len(shared) == 1 else 'them'} yet; "
                        "name your other Creators.")
    fmt = "xlsx" if str(raw.get("format") or "").lower() == "xlsx" and _XLSX_WORD.search(request) else "csv"
    problems = list(dict.fromkeys([*problems, *unresolved]))
    slots = {
        "recipe": None if problems else recipe.as_dict(),
        "format": fmt,
        "window": {"from": frm.isoformat(), "to": to.isoformat(), "tz": ctx.zone},
        "labels": {"dataset": name.replace("_", " ").capitalize(), "about": ds.about,
                   "creators": creator_names, "all_creators": len(creators),
                   "employees": employee_names if ds.employees else None,
                   "kinds": [rd.KIND_LABELS.get(k, k) for k in recipe.kinds],
                   "order": rd.order_label(recipe), "limit": recipe.limit},
        "columns": rd.columns(recipe),
        "filename": rd.filename(name, frm, to, fmt),
    }
    return ExportDraft(slots, list(dict.fromkeys([*notes, *assumptions])), problems), None


def export_summary(slots: dict[str, Any]) -> str:
    lb, w = slots["labels"], slots["window"]
    who = ", ".join(lb["creators"]) or "all your Creators"
    return (f"Export {lb['dataset'].lower()} for {who}, {w['from']} to {w['to']} ({w['tz']}), "
            f"as {'Excel' if slots['format'] == 'xlsx' else 'CSV'}. Nothing downloads until you press Download.")
