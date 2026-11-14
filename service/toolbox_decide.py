"""service/toolbox_decide.py — the Toolbox registry, pure (docs/plans/ultra-mode/issues/04-toolbox.md).

One list of tools (`TOOLS`) over existing relay routes, shared by the MCP server, the Ultra
loop and Do mode. Each `Tool` names its route (method + path) and a pydantic args model; the
JSON schema every LLM sees is generated from that model. `toolbox.call` runs a tool in-process
through the full HTTP stack with the caller's own credential; everything here is pure:

  validate_args   args → the model's dump, or per-field errors (before any request is built)
  build_request   args → (method, path, query, json body, headers); `account_id` binds the
                  Creator in the header + query (+ body for a POST) so the isolation
                  middleware, the route's own owner check and audit all see the same one
  shape_result    a route answer → the tool result: lists ≤50 rows (reports 200), strings ≤500
                  chars, ≤~24k chars, `row_count` + `truncated` (true when rows, a string or the
                  route's hasMore were cut; a non-list result carries it only then);
                  non-2xx → {error:{status,detail}}; untrusted text wrapped {"data_only": …}
  open_url        the app page the result opens in (`Open`), on the public app base
  as_mcp / as_openai / as_anthropic   the tool's schema in each client's shape
  route_refusal   a bearer's RAW request to a write tool's route must be one that tool could
                  have built (token_auth gates it): the token allowlist grants a whole route,
                  and these routes take untyped bodies wider than the tool's schema

Write tools (`effect="write"`, step 3; their args + checks live in toolbox_writes): `check`,
where the route can answer 2xx without doing all that was asked (it swallows a sub-failure, or
drops / rewrites a field), compares its answer with the args; a mismatch is an error result,
never success. A route that echoes the args or fails loudly needs none. A tool on a resource id
(a bio page) takes no `account_id` and sends no Creator: its route audits the resource's stored
one (audit_log.AUDIT_ACCOUNT).

Send tools (`effect="send"`, step 4; args + checks in toolbox_sends) carry OF-bound model text:
`model_text` names those arg paths and `text_kind` the chain stages (send_chain; issues/13). Never
on the token allowlist nor in MCP tools/list; `toolbox.call` runs one only for a plan step (the
Ultra executor). A send's `check` failing means "may have gone out" (the executor's uncertain).
auto_mass / auto_story make a switched-on automation rule (`body`: flat args → the rule route's body).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, Field, ValidationError

import toolbox_sends as ts
import toolbox_writes as tw
from toolbox_args import CREATOR as _CREATOR, Args

Effect = Literal["read", "write", "send"]
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
MAX_ROWS = 50
REPORT_ROWS = 200
MAX_STR = 500
MAX_CHARS = 24_000
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::\d{1,5})?")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class Open:
    """The app page a result opens in. `path` may hold `{name}` placeholders, each filled from
    `fields` (name → "args.<key>" or "result.<key>", explicit: routes name ids differently).
    `by` = (args key, ((value, path), …)): a page per value of one arg, `path` the default.
    A placeholder with no value (an error result: no id came back) → no page."""
    path: str
    fields: tuple[tuple[str, str], ...] = ()
    by: tuple[str, tuple[tuple[str, str], ...]] | None = None

    def paths(self) -> tuple[str, ...]:
        return (self.path, *(p for _, p in (self.by[1] if self.by else ())))


# (validated args, the route's 2xx answer) → None when the answer shows what was asked, else why
# not (the tool result is then an error).
Check = Callable[[Mapping[str, Any], Any], "str | None"]


@dataclass(frozen=True)
class Shape:
    """How a route answer is cut down. `rows`: the key of the answer's main list; `keep`: the
    dotted fields kept per row (None = all); `urls`: top-level fields made absolute on the
    public app base (a download link)."""
    rows: str | None = None
    max_rows: int = MAX_ROWS
    keep: tuple[str, ...] | None = None
    urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    method: str
    path: str
    args: type[Args]  # unknown keys refused
    effect: Effect
    long: bool = False
    untrusted: bool = False
    shape: Shape = field(default_factory=Shape)
    open: Open | None = None
    # Frozen in step 2 (ticket 13): arg paths carrying OF-bound model text, and its chain stages; text_kind also
    # picks a send's card rows (auto_story carries no text).
    model_text: tuple[str, ...] = ()
    text_kind: Literal["mass", "post", "auto_mass", "auto_story"] | None = None
    # Constant params the tool always sends (not in the schema), e.g. report_run's format=json.
    fixed: tuple[tuple[str, Any], ...] = ()
    # A route body shaped unlike the args (an automation rule's nested payload): validated args → body.
    body: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # Write tools: the echo check (module doc); `replaces`: overwrites (and deletes) what was there
    # before, e.g. an image file → MCP destructiveHint.
    check: Check | None = None
    replaces: bool = False
    # The Ultra plan card's step heading; None = the name in Title Case (ultra_decide.title).
    title: str | None = None


# ── v1 read tools ───────────────────────────────────────────────────────────

class NoArgs(Args):
    pass


class CreatorArgs(Args):
    account_id: str = Field(description=_CREATOR)


class StatsArgs(Args):
    from_: str | None = Field(None, alias="from", description="Window start, YYYY-MM-DD (default: 30 days ago).")
    to: str | None = Field(None, description="Window end, YYYY-MM-DD (default: now).")
    account_id: str | None = Field(None, description="One Creator's id; omit for every Creator.")
    engagement: bool = Field(False, description="Also count PPVs sent, fans chatted and reply time.")


class VaultSearchArgs(Args):
    account_id: str = Field(description=_CREATOR)
    query: str = Field("", description="Words to find in the media's AI description, tags or OF search terms.")
    type: Literal["all", "photo", "video", "gif", "audio"] = Field("all", description="Media type.")
    tags: list[str] = Field(default_factory=list, description="Only media carrying every one of these tags.")
    not_nude: bool = Field(False, description="Only media the AI currently reads as nothing bare and no toy "
                                              "(unread media left out).")
    limit: int = Field(30, ge=1, le=30, description="At most this many items (≤30).")


class RulesArgs(Args):
    account_id: str | None = Field(None, description="One Creator's id; omit for every Creator.")


_RECIPE = ("The report recipe: {dataset, window: {preset} or {from, to}, creators?, employees?, kinds?, "
           "group_by?, metrics?, sort?, limit?}. Datasets, metrics, presets and limits: call report_catalogue "
           "first. Creators and employees are ids or exact names.")


class ReportArgs(Args):
    recipe: dict[str, Any] = Field(description=_RECIPE)


class ReportFileArgs(Args):
    recipe: dict[str, Any] = Field(description=_RECIPE)
    format: Literal["csv", "xlsx"] = Field("csv", description="File format.")


_BIO_OPEN = Open("/growth/bio-pages/{profile_id}", fields=(("profile_id", "args.pid"),))

_REPORT_OPEN = Open("/analytics/creator-reports", by=("recipe.dataset", (
    ("employee_sales", "/analytics/employee-reports"),
    ("chat_activity", "/analytics/message-dashboard"),
    ("fan_spend", "/analytics/fan-reports"),
)))
_VAULT = Open("/growth/vault-pro")

TOOLS: tuple[Tool, ...] = (
    Tool("creators_list", "List the Agency's Creators (OnlyFans models): id, name, username, session state.",
         "GET", "/admin/accounts", NoArgs, "read", open=Open("/creators"),
         shape=Shape(rows="accounts", keep=("id", "nickname", "name", "username", "platform", "is_active",
                                            "has_session", "session_dead_at", "proxy_down"))),
    Tool("stats_per_model", "Per-Creator money and fan figures for a window: revenue by kind, new and active "
         "subscribers, LTV, ARPU, refunds, spenders. Amounts are cents.",
         "GET", "/admin/stats/per-model", StatsArgs, "read", open=Open("/analytics/creator-reports"),
         shape=Shape(rows="per_model")),
    Tool("vault_search", "Search one Creator's vault (local mirror) by the media's AI description and tags. "
         "Returns media ids with their description, tags and explicitness.",
         "GET", "/admin/vault-ai/items", VaultSearchArgs, "read", untrusted=True, open=_VAULT,
         shape=Shape(rows="list", max_rows=30, keep=(
             "id", "type", "createdAt", "duration", "_ai.description", "_ai.video_description", "_ai.tags",
             "_ai.explicitness_tier", "_ai.story_suitable", "_ai.describe_status", "_thumb"))),
    Tool("of_folders_list", "List one Creator's OnlyFans vault folders with media counts.",
         "GET", "/admin/vault-ai/of-folders", CreatorArgs, "read", open=_VAULT, shape=Shape(rows="list")),
    Tool("describe_all_status", "Whether the AI describe pass over one Creator's vault is running, and its progress.",
         "GET", "/admin/vault-ai/describe-all/status", CreatorArgs, "read", open=_VAULT),
    Tool("describe_all_plan", "How many of one Creator's vault media are not AI-described yet (so not found by "
         "vault_search), with the describe budget. Starting a describe is the owner's, in Vault Pro.",
         "GET", "/admin/vault-ai/describe-all/plan", CreatorArgs, "read", open=_VAULT),
    Tool("automation_kinds", "The automation kinds a rule can have, with what each one's payload takes.",
         "GET", "/admin/automation-kinds", NoArgs, "read", open=Open("/growth/auto-mass"),
         shape=Shape(rows="kinds", max_rows=200)),
    Tool("automation_rules_list", "List automation rules (Auto mass, Smart Messages, Auto story …) with on/off, "
         "last run and next due.",
         "GET", "/admin/automation-rules", RulesArgs, "read", open=Open("/growth/auto-mass"),
         shape=Shape(rows="rules")),
    Tool("bio_pages_list", "List the Agency's bio (link-in-bio) pages: id, Creator, public URL, background "
         "picture (empty: none), links, 30-day views and clicks.",
         "GET", "/admin/bio-pages", NoArgs, "read", open=Open("/growth/bio-pages"), shape=Shape(rows="profiles")),
    Tool("bio_page_get", "One bio page: its Creator, public URL, avatar, background picture and links (ids, titles, "
         "destinations, icons, 18+ and tracking flags, background images).",
         "GET", "/admin/bio-pages/{pid}", tw.BioPageArgs, "read", open=_BIO_OPEN, shape=Shape(rows="links")),
    Tool("report_catalogue", "The report datasets a recipe may name, their group-bys, metrics, kinds and "
         "window presets. Read before report_run; a report it does not list is not available.",
         "GET", "/admin/reports/catalogue", NoArgs, "read", open=Open("/analytics/creator-reports")),
    Tool("report_run", "Run a report recipe over the Agency's own Creators and Employees; returns up to 200 "
         "rows as JSON. For the whole table as a file, use report_file.",
         "POST", "/admin/reports/run", ReportArgs, "read", untrusted=True, open=_REPORT_OPEN,
         shape=Shape(rows="rows", max_rows=REPORT_ROWS), fixed=(("format", "json"),)),
    Tool("report_file", "Build a report recipe's whole table as a CSV or Excel file; returns a download_url "
         "valid 15 minutes for the same access token (Authorization: Bearer).",
         "POST", "/admin/reports/files", ReportFileArgs, "read", open=_REPORT_OPEN,
         shape=Shape(urls=("download_url",))),
    # Writes. Folder tools act on the Creator's OnlyFans vault over her own session (OF scopes the
    # folder id to her), so they take account_id; bio page tools send none (the route audits the page's).
    Tool("of_folder_create", "Create a folder in one Creator's OnlyFans vault, optionally with vault media in "
         "it. Returns the new folder's id. Not idempotent: each call makes a new folder, so never repeat a "
         "call that may have worked.",
         "POST", "/admin/vault-ai/of-folders", tw.FolderCreateArgs, "write", open=_VAULT, check=tw.check_folder_create),
    Tool("of_folder_add", "Add vault media to one of a Creator's existing OnlyFans vault folders.",
         "POST", "/admin/vault-ai/of-folders/{list_id}/add", tw.FolderAddArgs, "write", open=_VAULT),
    Tool("bio_page_create", "Create a bio (link-in-bio) page. Given a Creator, it starts with a link to her "
         "OnlyFans. Returns the page with its id and links.",
         "POST", "/admin/bio-pages", tw.BioPageCreateArgs, "write", check=tw.check_bio_page_create,
         open=Open("/growth/bio-pages/{profile_id}", fields=(("profile_id", "result.profile.id"),)),
         shape=Shape(rows="links")),
    Tool("bio_avatar_from_vault", "Set a bio page's avatar to a photo from its Creator's vault.",
         "POST", "/admin/bio-pages/{pid}/avatar/vault", tw.BioVaultImageArgs, "write", open=_BIO_OPEN,
         shape=Shape(rows="links"), replaces=True),
    Tool("bio_page_background", "Set a bio page's background picture (behind the whole page, every screen size) to "
         "a photo from its Creator's vault.",
         "POST", "/admin/bio-pages/{pid}/background/vault", tw.BioVaultImageArgs, "write", open=_BIO_OPEN,
         shape=Shape(rows="links"), replaces=True),
    Tool("bio_link_add", "Add a link (button) to the end of a bio page. Returns the new link as `link` "
         "(its id is the lid for bio_link_bg_from_vault) and the page.",
         "POST", "/admin/bio-pages/{pid}/links", tw.BioLinkAddArgs, "write", open=_BIO_OPEN,
         check=tw.check_bio_link_add, shape=Shape(rows="links")),
    Tool("bio_link_bg_from_vault", "Set a bio page link's background image to a photo from the page's Creator's "
         "vault.",
         "POST", "/admin/bio-pages/{pid}/links/{lid}/background/vault", tw.BioLinkBgArgs, "write", open=_BIO_OPEN,
         shape=Shape(rows="links"), replaces=True),
    # Sends (step 4): only from an owner-approved plan; their text is chained at propose (send_chain).
    Tool("mass_send", "Send (or schedule) a mass message from one Creator to lists and/or fans, optionally "
         "priced with vault media. Only inside propose_plan; the owner approves it in the browser.",
         "POST", "/api/of/v2/messages/queue", ts.MassSendArgs, "send", open=Open("/growth/smart-messages"),
         model_text=("text",), text_kind="mass", check=ts.check_mass_send,
         fixed=(("require_recipients", True),), title="Mass message"),
    Tool("post_create", "Publish (or schedule) a post on one Creator's OnlyFans feed, optionally priced with "
         "vault media. Only inside propose_plan; the owner approves it in the browser.",
         "POST", "/api/of/v2/posts", ts.PostCreateArgs, "send", open=Open("/of-manager/home"),
         model_text=("text",), text_kind="post", check=ts.check_post_create, title="Post"),
    Tool("auto_mass", "Make a switched-on Auto mass: a mass message from one Creator, with random photos from a "
         "vault folder, now and then every N hours until switched off. Only inside propose_plan; the owner approves "
         "it in the browser.",
         "POST", "/admin/automation-rules", ts.AutoMassArgs, "send", open=Open("/growth/auto-mass"),
         model_text=("text",), text_kind="auto_mass", check=ts.check_rule,
         body=lambda a: ts.rule_body("auto_mass", a), title="Auto mass"),
    Tool("auto_story", "Make a switched-on Auto story: random photos from a vault folder posted as one Creator's "
         "stories, now and then every N hours until switched off. Only inside propose_plan; the owner approves it "
         "in the browser.",
         "POST", "/admin/automation-rules", ts.AutoStoryArgs, "send", open=Open("/growth/auto-story"),
         text_kind="auto_story", check=ts.check_rule, body=lambda a: ts.rule_body("auto_story", a),
         title="Auto story"),
)

# What an owner access token (MCP) may call: every tool but send-class ones, which run
# only from an owner-approved plan. token_auth's allowlist and MCP tools/list both read it.
def token_tools() -> list[Tool]:
    return [t for t in TOOLS if t.effect != "send"]


# ── args ────────────────────────────────────────────────────────────────────

class ArgsError(Exception):
    """Refused args: one reason per field."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def validate_args(tool: Tool, args: Mapping[str, Any] | None) -> dict[str, Any]:
    """The args as the route takes them (aliases, defaults filled), or ArgsError per field."""
    if args is not None and not isinstance(args, Mapping):
        raise ArgsError({"args": "must be an object"})
    try:
        model = tool.args.model_validate(dict(args or {}))
    except ValidationError as e:
        raise ArgsError({".".join(str(p) for p in err["loc"]) or "args": err["msg"]
                         for err in e.errors()}) from None
    return model.model_dump(by_alias=True)


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, Any]
    json: dict[str, Any] | None
    headers: dict[str, str]


def build_request(tool: Tool, args: Mapping[str, Any]) -> Request:
    """`args` (validated) → the route request. Path placeholders are filled first; a GET/DELETE
    sends the rest as query, a write as a JSON body. `account_id` is also the X-Account-Id
    header and `?account_id=` (the isolation middleware scans query and path only)."""
    rest = {**dict(tool.fixed), **{k: v for k, v in args.items() if v is not None}}
    path = _fill(tool.path, rest)
    for name in _PLACEHOLDER.findall(tool.path):
        rest.pop(name)
    headers: dict[str, str] = {}
    query: dict[str, Any] = {}
    aid = rest.get("account_id")
    if aid is not None:
        headers["X-Account-Id"] = str(aid)
        query["account_id"] = str(aid)
    if tool.method in ("GET", "DELETE"):
        return Request(tool.method, path, {**rest, **query}, None, headers)
    return Request(tool.method, path, query, tool.body(rest) if tool.body else rest, headers)


def _fill(template: str, values: Mapping[str, Any]) -> str:
    path = template
    for name in _PLACEHOLDER.findall(template):
        value = str(values.get(name) if values.get(name) is not None else "")
        if not value or "/" in value or value in (".", ".."):
            raise ArgsError({name: "not a valid id"})
        path = path.replace("{" + name + "}", value)
    return path


def write_tool(method: str, template: str) -> Tool | None:
    return next((t for t in TOOLS if t.effect == "write" and (t.method, t.path) == (method, template)), None)


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def route_refusal(tool: Tool, path: str, path_params: Mapping[str, Any], query: Mapping[str, Any],
                  header_account: str | None, body: Any) -> str | None:
    """Why a bearer's raw request to `tool`'s route is not one the tool could have built, or None.
    One source of truth, `build_request`: the body + path params are validated as the tool's args
    and rebuilt; the raw path, query, X-Account-Id and body must equal the rebuilt request exactly
    (JSON-typed: 1 is not true, defaults sent). So a tool with no account_id arg (a bio page tool:
    its route audits the page's stored Creator) refuses any header or query Creator."""
    if not isinstance(body, Mapping):
        return "the body must be a JSON object"
    try:
        want = build_request(tool, validate_args(tool, {**body, **path_params}))
    except ArgsError as e:
        return f"not what {tool.name} takes: {e}"
    sent = Request(tool.method, path, dict(query), dict(body),
                   {} if header_account is None else {"X-Account-Id": header_account})
    for label, part in (("path", "path"), ("query", "query"), ("X-Account-Id", "headers"), ("body", "json")):
        if _canon(getattr(sent, part)) != _canon(getattr(want, part)):
            return f"its {label} is not what {tool.name} sends (want {_canon(getattr(want, part))[:300]})"
    return None


# ── results ─────────────────────────────────────────────────────────────────

def _get(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(obj, Mapping):
            return None
        obj = obj.get(part)
    return obj


def _pick(row: Any, keep: tuple[str, ...]) -> Any:
    if not isinstance(row, Mapping):
        return row
    out: dict[str, Any] = {}
    for dotted in keep:
        value = _get(row, dotted)
        if value is None:
            continue
        *parents, leaf = dotted.split(".")
        node = out
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = value
    return out


def _clipped(v: Any) -> tuple[Any, bool]:
    """`v` with every string cut to MAX_STR chars (+ "…"), and whether any was cut."""
    if isinstance(v, str):
        return (v, False) if len(v) <= MAX_STR else (v[:MAX_STR] + "…", True)
    if isinstance(v, Mapping):
        pairs = {k: _clipped(x) for k, x in v.items()}
        return {k: x for k, (x, _) in pairs.items()}, any(c for _, c in pairs.values())
    if isinstance(v, (list, tuple)):
        items = [_clipped(x) for x in v]
        return [x for x, _ in items], any(c for _, c in items)
    return v, False


def _clip(v: Any) -> Any:
    return _clipped(v)[0]


def _size(v: Any) -> int:
    return len(json.dumps(v, ensure_ascii=False, default=str))


def error(status: int, detail: Any) -> dict[str, Any]:
    return {"error": {"status": status, "detail": _clip(detail)}}


def shape_result(tool: Tool, status: int, body: Any, *, base: str | None = None) -> dict[str, Any]:
    """A route answer (`body`: parsed JSON, else text) → the tool result."""
    if not 200 <= status < 300:
        detail = body.get("detail", body) if isinstance(body, Mapping) else body
        if isinstance(body, Mapping) and "errors" in body:
            detail = {"detail": detail, "errors": body["errors"]}
        return error(status, detail if detail not in (None, "") else "request failed")
    data: dict[str, Any] = dict(body) if isinstance(body, Mapping) else {"result": body}
    sh = tool.shape
    meta: dict[str, Any] = {}
    rows = data.get(sh.rows) if sh.rows else None
    if isinstance(rows, list):
        total = data.get("row_count") if isinstance(data.get("row_count"), int) else len(rows)
        kept = [_pick(r, sh.keep) if sh.keep else r for r in rows[:sh.max_rows]]
        data[sh.rows] = kept
        meta = {"row_count": max(total, len(rows)), "truncated": bool(data.get("truncated")) or len(rows) > len(kept)}
    data, clipped = _clipped(data)
    # Anything cut is a cut result: a clipped string anywhere, or the route's own hasMore (more pages upstream).
    if clipped or data.get("hasMore") is True:
        meta["truncated"] = True
    for key in sh.urls:
        if isinstance(data.get(key), str) and data[key].startswith("/") and base:
            data[key] = base + data[key]
    while _size(data) > MAX_CHARS and isinstance(rows, list) and data[sh.rows]:
        data[sh.rows] = data[sh.rows][:len(data[sh.rows]) // 2]
        meta["truncated"] = True
    if _size(data) > MAX_CHARS:
        return error(413, "result too large for one tool call; narrow the request")
    if isinstance(rows, list):
        data.pop("row_count", None)
        data.pop("truncated", None)
    out = {"data_only": data} if tool.untrusted else data
    return {**out, **meta}


# ── open_url ────────────────────────────────────────────────────────────────

def public_base(forwarded_host: str | None, forwarded_proto: str | None, configured: str | None = None) -> str | None:
    """The public app origin: `configured` (APP_PUBLIC_URL), else X-Forwarded-Host/Proto (first
    hop). Never the relay's own Host: behind Next that is the RELAY_URL host (spike)."""
    if configured and configured.strip():
        return configured.strip().rstrip("/")
    host = (forwarded_host or "").split(",")[0].strip().lower()
    proto = (forwarded_proto or "https").split(",")[0].strip().lower()
    if proto not in ("http", "https") or not _HOST.fullmatch(host):
        return None
    return f"{proto}://{host}"


def open_path(op: Open | None, args: Mapping[str, Any], result: Any) -> str | None:
    if op is None:
        return None
    path = op.path
    if op.by is not None:
        path = dict(op.by[1]).get(_get(args, op.by[0]), op.path)
    sources = {"args": args, "result": result}
    for name, src in op.fields:
        kind, _, key = src.partition(".")
        value = _get(sources.get(kind), key)
        if value is None or "/" in str(value):
            return None
        path = path.replace("{" + name + "}", str(value))
    return None if _PLACEHOLDER.search(path) else path


def open_url(base: str | None, op: Open | None, args: Mapping[str, Any], result: Any) -> str | None:
    """`base` + the page path; the bare path when no public base is known."""
    path = open_path(op, args, result)
    if path is None:
        return None
    return (base or "") + path


# ── client schemas ──────────────────────────────────────────────────────────

def _clean(node: Any) -> Any:
    """Pydantic's schema without titles, with `X | None` collapsed to X (optional = not required).
    A property NAMED title (bio_link_add's) is a property, not a schema title: kept."""
    if isinstance(node, dict):
        any_of = node.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2 and {"type": "null"} in any_of:
            other = next(a for a in any_of if a != {"type": "null"})
            node = {**{k: v for k, v in node.items() if k != "anyOf"}, **other}
        return {k: ({n: _clean(s) for n, s in v.items()} if k == "properties" and isinstance(v, dict) else _clean(v))
                for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_clean(x) for x in node]
    return node


def args_schema(args: type[BaseModel]) -> dict[str, Any]:
    schema = _clean(args.model_json_schema(by_alias=True))
    schema.setdefault("properties", {})
    schema["additionalProperties"] = False
    return schema


def mcp_schema(name: str, description: str, args: type[BaseModel], effect: Effect,
               replaces: bool = False) -> dict[str, Any]:
    """An MCP tools/list entry from its parts alone: a Tool's (`as_mcp`), or a tool with no
    route behind it (mcp_api's builtins)."""
    return {"name": name, "description": description, "inputSchema": args_schema(args),
            "annotations": {"readOnlyHint": effect == "read", "destructiveHint": effect == "send" or replaces,
                            "openWorldHint": effect == "send"}}


def as_mcp(tool: Tool) -> dict[str, Any]:
    return mcp_schema(tool.name, tool.description, tool.args, tool.effect, tool.replaces)


def as_openai(tool: Tool) -> dict[str, Any]:
    return {"type": "function", "function": {"name": tool.name, "description": tool.description,
                                             "parameters": args_schema(tool.args)}}


def as_anthropic(tool: Tool) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "input_schema": args_schema(tool.args)}
