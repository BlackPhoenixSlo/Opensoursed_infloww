/**
 * smartListEditorState — the Smart list editor: its field catalogue (FIELD_DEFS, the ops and defaults per field,
 * the UI ⇄ wire rule conversion) and its state as a pure reducer: the name, the match, the condition rows, the
 * last "Preview count" answer and the error. Any rule or match edit bumps `rev` and drops the preview and the error
 * (the count must be of the rules on screen; the user runs Preview again), and a preview answer (or its error) for
 * an older `rev` is dropped, never shown. `validateRule` gates Save and Preview: a numeric field needs a number, a
 * `between` both bounds, lower ≤ upper.
 */

import type {
  SmartField, SmartOp, SmartPreview, SmartRule, SmartRules, SmartScope, SmartTimeframe,
} from "@/hooks/useSmartLists";

export type Kind = "money" | "days" | "date" | "enum" | "tag";

export interface FieldDef {
  field: SmartField;
  label: string;
  group: string;
  kind: Kind;
  scoped?: boolean;     // creator | org
  timeframe?: boolean;  // all | today | … | 90d
}

export const FIELD_DEFS: FieldDef[] = [
  { field: "lifetime_spend",       group: "Spend", label: "Lifetime spend (OnlyFans total)", kind: "money" },
  { field: "total_spend",          group: "Spend", label: "Total spend",              kind: "money", scoped: true, timeframe: true },
  { field: "ppv_spend",            group: "Spend", label: "Messages / PPV spend",     kind: "money", scoped: true, timeframe: true },
  { field: "tips_spend",           group: "Spend", label: "Tips spend",               kind: "money", scoped: true, timeframe: true },
  { field: "subscription_spend",   group: "Spend", label: "Subscription spend",       kind: "money", scoped: true, timeframe: true },
  { field: "highest_spend",        group: "Spend", label: "Highest single purchase",  kind: "money", scoped: true, timeframe: true },
  { field: "last_spend_amount",    group: "Spend", label: "Last purchase amount",     kind: "money", scoped: true },
  { field: "recent_spend",         group: "Spend", label: "Spend in the last N days", kind: "money" },
  { field: "last_purchase_at",     group: "Activity", label: "Last purchase",         kind: "date", scoped: true },
  { field: "last_message_sent_at", group: "Activity", label: "Last message sent",     kind: "date" },
  { field: "last_active_days",     group: "Activity", label: "Days since active",     kind: "days" },
  { field: "idle_days",            group: "Activity", label: "Last purchase, message or subscribe", kind: "date" },
  { field: "status",               group: "Subscription", label: "Subscription status", kind: "enum" },
  { field: "renew",                group: "Subscription", label: "Auto-renew",        kind: "enum" },
  { field: "sub_start",            group: "Subscription", label: "Subscribed",        kind: "date" },
  { field: "expires_at",           group: "Subscription", label: "Subscription expires", kind: "date" },
  { field: "resubscribed_at",      group: "Subscription", label: "Resubscribed",      kind: "date" },
  { field: "tag",                  group: "Tags", label: "Tag",                      kind: "tag" },
];

export const ENUM_VALUES: Partial<Record<SmartField, string[]>> = {
  status: ["active", "expired"],
  renew: ["on", "off"],
};

const NUMERIC_OPS: SmartOp[] = [">=", "<=", ">", "<", "==", "!=", "between"];

export function defOf(field: SmartField): FieldDef {
  return FIELD_DEFS.find((f) => f.field === field) ?? FIELD_DEFS[0];
}

export function opsFor(field: SmartField): SmartOp[] {
  const k = defOf(field).kind;
  if (k === "money" || k === "days") return NUMERIC_OPS;
  if (k === "date") {
    return field === "expires_at"
      ? ["within_next", "within_last", "more_than", "between"]
      : ["within_last", "more_than", "between"];
  }
  if (k === "enum") return ["==", "!="];
  return ["has", "not_has"];
}

/** UI rule row — values kept as strings (dollars for money, days for dates); converted to the wire shape (cents /
 *  days) on save. */
export interface RuleUI {
  field: SmartField; op: SmartOp; value: string; value2: string; days: string;
  scope: SmartScope; timeframe: SmartTimeframe;
}

export const EMPTY_RULE: RuleUI = {
  field: "lifetime_spend", op: ">=", value: "100", value2: "", days: "30",
  scope: "creator", timeframe: "all",
};

function defaultValue(field: SmartField): string {
  const k = defOf(field).kind;
  if (k === "enum") return ENUM_VALUES[field]![0];
  if (k === "tag") return "";
  return k === "money" ? "100" : "30";
}

export function toUI(r: SmartRule): RuleUI {
  const money = defOf(r.field).kind === "money";
  const show = (v: unknown) => String(money ? Number(v) / 100 : v ?? "");
  const pair = Array.isArray(r.value) ? r.value : null;
  return {
    field: r.field, op: r.op,
    value: pair ? show(pair[0]) : show(r.value),
    value2: pair ? show(pair[1]) : "",
    days: String(r.days ?? 30),
    scope: r.scope ?? "creator",
    timeframe: r.timeframe ?? "all",
  };
}

export function fromUI(r: RuleUI): SmartRule {
  const d = defOf(r.field);
  if (d.kind === "enum" || d.kind === "tag") return { field: r.field, op: r.op, value: r.value };
  const num = (s: string) =>
    d.kind === "money" ? Math.round(Number(s || 0) * 100) : Number(s || 0);
  const out: SmartRule = {
    field: r.field, op: r.op,
    value: r.op === "between" ? [num(r.value), num(r.value2)] : num(r.value),
  };
  if (d.scoped) out.scope = r.scope;
  if (d.timeframe) out.timeframe = r.timeframe;
  if (r.field === "recent_spend") out.days = Math.max(1, Math.round(Number(r.days || 30)));
  return out;
}

const isNum = (v: string) => Number.isFinite(Number(v));

/** Why a row can't be saved or previewed, or null. A numeric field (money, days, date) needs its value as a number;
 *  a `between` both bounds as numbers, lower ≤ upper; "Spend in the last N days" its days as a number. */
export function validateRule(r: RuleUI): string | null {
  const kind = defOf(r.field).kind;
  if (kind === "enum" || kind === "tag") return null;
  const lo = r.value.trim(), hi = r.value2.trim();
  if (r.op === "between") {
    if (!lo || !hi) return "Enter both bounds";
    if (!isNum(lo) || !isNum(hi)) return "Bounds must be numbers";
    if (Number(hi) < Number(lo)) return "The upper bound must be at least the lower one";
  } else {
    if (!lo) return "Enter a value";
    if (!isNum(lo)) return "The value must be a number";
  }
  if (r.field === "recent_spend" && !(r.days.trim() && isNum(r.days))) return "Enter the number of days";
  return null;
}

export interface EditorState {
  name: string;
  /** Save was tried with no name. */
  nameErr: boolean;
  match: "all" | "any";
  rows: RuleUI[];
  /** Bumped by every rule / match edit: a preview of an older rev is dropped. */
  rev: number;
  /** The last preview, of `rev`'s rules; null after any rule / match edit. */
  preview: SmartPreview | null;
  /** The last Preview or Save error; null after any rule / match edit. */
  err: string | null;
}

export type Action =
  | { type: "name"; name: string }
  /** Save was tried and `saveRefusal` gave `reason`: a missing name is flagged; invalid rows show their own reason. */
  | { type: "saveRefused"; reason: SaveRefusal }
  | { type: "match"; match: "all" | "any" }
  /** Field change: the op, value and value2 reset to the new field's defaults. */
  | { type: "field"; i: number; field: SmartField }
  | { type: "row"; i: number; patch: Partial<Omit<RuleUI, "field">> }
  | { type: "add" }
  | { type: "remove"; i: number }
  /** A preview answer for the rules at `rev`. */
  | { type: "previewed"; rev: number; data: SmartPreview }
  /** A preview of the rules at `rev` failed. */
  | { type: "previewFailed"; rev: number; message: string }
  /** Preview or Save started: the old error goes. */
  | { type: "start" }
  | { type: "saveFailed"; message: string };

export function initEditor(name: string, rules: SmartRules | null): EditorState {
  return {
    name, nameErr: false,
    match: rules?.match ?? "all",
    rows: rules?.rules?.length ? rules.rules.map(toUI) : [{ ...EMPTY_RULE }],
    rev: 0, preview: null, err: null,
  };
}

/** A rules edit: new rows / match, the preview and the error dropped. */
const edited = (s: EditorState, patch: Partial<Pick<EditorState, "rows" | "match">>): EditorState =>
  ({ ...s, ...patch, rev: s.rev + 1, preview: null, err: null });

export function rulesReducer(s: EditorState, a: Action): EditorState {
  switch (a.type) {
    case "name":
      return { ...s, name: a.name, nameErr: false };
    case "saveRefused":
      return a.reason === "name" && !s.nameErr ? { ...s, nameErr: true } : s;
    case "match":
      return a.match === s.match ? s : edited(s, { match: a.match });
    case "field":
      return edited(s, { rows: s.rows.map((r, j) => (j === a.i
        ? { ...r, field: a.field, op: opsFor(a.field)[0], value: defaultValue(a.field), value2: "" }
        : r)) });
    case "row":
      return edited(s, { rows: s.rows.map((r, j) => (j === a.i ? { ...r, ...a.patch } : r)) });
    case "add":
      return edited(s, { rows: [...s.rows, { ...EMPTY_RULE }] });
    case "remove":
      return edited(s, { rows: s.rows.filter((_, j) => j !== a.i) });
    case "previewed":
      return a.rev === s.rev ? { ...s, preview: a.data, err: null } : s;
    case "previewFailed":
      return a.rev === s.rev ? { ...s, err: a.message } : s;
    case "start":
      return s.err === null ? s : { ...s, err: null };
    case "saveFailed":
      return { ...s, err: a.message };
  }
}

/** Every row valid: Preview is allowed (and the Save button enabled). */
export const rulesValid = (s: Pick<EditorState, "rows">): boolean => s.rows.every((r) => validateRule(r) === null);

export type SaveRefusal = "name" | "rules";

/** Why Save may not write (no name first, then an invalid row), or null. */
export const saveRefusal = (s: Pick<EditorState, "name" | "rows">): SaveRefusal | null =>
  !s.name.trim() ? "name" : rulesValid(s) ? null : "rules";

/** The wire rules for Preview and Save. */
export const buildRules = (s: Pick<EditorState, "match" | "rows">): SmartRules =>
  ({ match: s.match, rules: s.rows.map(fromUI) });
