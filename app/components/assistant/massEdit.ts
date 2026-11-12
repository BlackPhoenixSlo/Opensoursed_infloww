/**
 * Do-mode's `mass_edit` (docs/spec/assistant-do-mode.md D11): change settings on EXISTING Auto mass rules — here, or
 * on every model. The server drafts the plan (which rules, each one's before → after; service/assistant_edit.py) and
 * applies it (POST /admin/assistant/edit/apply, re-applied to the fresh rows, never a client payload). This file is the
 * pure half the plan card and the result list read (massEdit.test.ts): no cursor, no editor — the apply is one call.
 */

/** A change field, as the server names it (assistant_edit LABELS). */
export type EditField =
  | "unsend_after_hours" | "online_only" | "every_seconds" | "exclude_last_chat_hours" | "price" | "media_count"
  | "is_enabled";

export interface EditDiff { field: EditField; label: string; before: unknown; after: unknown }

export interface EditRule {
  id: number;
  account_id: string;
  account_name: string;
  name: string;
  is_enabled: boolean;
  /** What the card saw; the apply skips a rule changed since. */
  version: string;
  diffs: EditDiff[];
}

/** The clean change spec (assistant_edit.clean_changes): a key present = changing it. */
export interface EditChanges {
  unsend_after_hours?: number;
  online_only?: boolean;
  every_seconds?: number;
  exclude_last_chat_hours?: number;
  price?: number;
  media_count?: number;
  disable_rule?: true;
}

export interface MassEditSlots {
  scope: "this" | "all";
  match: string | null;
  changes: EditChanges;
  rules: EditRule[];
  /** Matching rules that already have the change. */
  already: number;
  skipped: Array<{ id: number; name: string; account_name?: string; reason: string }>;
}

/** One rule's apply outcome (the route's `results[]`). */
export interface EditResult { id: number; ok: boolean; reason?: string }

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmtNum = (n: number) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100));
const hours = (h: number) => (h < 1 ? `${fmtNum(Math.round(h * 60))} min` : `${fmtNum(h)}h`);

/** A diff value in plain words: "8h", "never", "$15", "on". */
export function fmtValue(field: EditField, v: unknown): string {
  const n = num(v);
  switch (field) {
    case "unsend_after_hours": return n && n > 0 ? hours(n) : "never";
    case "exclude_last_chat_hours": return n && n > 0 ? hours(n) : "off";
    case "every_seconds": return n && n > 0 ? hours(n / 3600) : "—";
    case "price": return n && n > 0 ? `$${fmtNum(n)}` : "free";
    case "media_count": return n && n > 0 ? String(n) : "1";
    case "online_only":
    case "is_enabled": return v ? "on" : "off";
  }
}

/** "Unsend after 8h → never". */
export const diffLine = (d: EditDiff) => `${d.label} ${fmtValue(d.field, d.before)} → ${fmtValue(d.field, d.after)}`;

/** The change spec's lines, the card's head: "Unsend after → never", "Switch off". */
export function changeLines(c: EditChanges): string[] {
  const out: string[] = [];
  if (c.unsend_after_hours !== undefined) out.push(`Unsend after → ${fmtValue("unsend_after_hours", c.unsend_after_hours)}`);
  if (c.every_seconds !== undefined) out.push(`Every → ${fmtValue("every_seconds", c.every_seconds)}`);
  if (c.online_only !== undefined) out.push(`Online fans only → ${fmtValue("online_only", c.online_only)}`);
  if (c.exclude_last_chat_hours !== undefined) {
    out.push(`Skip fans chatted with recently → ${fmtValue("exclude_last_chat_hours", c.exclude_last_chat_hours)}`);
  }
  if (c.price !== undefined) out.push(`Price → ${fmtValue("price", c.price)}`);
  if (c.media_count !== undefined) out.push(`Photos per mass → ${c.media_count}`);
  if (c.disable_rule) out.push("Switch off");
  return out;
}

/** An enabled rule whose change makes it send MORE (or charge differently) right away: a shorter interval, fewer
 *  skip-recent hours, online-only off, a price change. */
export function isLiveIncrease(r: EditRule): boolean {
  if (!r.is_enabled) return false;
  return r.diffs.some((d) => {
    const b = num(d.before), a = num(d.after);
    switch (d.field) {
      case "every_seconds": return b !== null && a !== null && a < b;
      case "exclude_last_chat_hours": return (b ?? 0) > (a ?? 0);
      case "online_only": return d.before === true && d.after === false;
      case "price": return true;
      default: return false;
    }
  });
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

export interface EditPlanText {
  /** "3 rules · 2 models". */
  headline: string;
  changes: string[];
  groups: Array<{ model: string; rules: Array<{ id: number; name: string; live: boolean; lines: string[] }> }>;
  /** "1 already set", "Skipped “X”: reason". */
  notes: string[];
}

/** The mass_edit plan card's text, pure. Rules grouped per model in the server's order. */
export function editPlanText(s: MassEditSlots): EditPlanText {
  const groups: EditPlanText["groups"] = [];
  for (const r of s.rules) {
    let g = groups.find((x) => x.model === r.account_name);
    if (!g) groups.push(g = { model: r.account_name, rules: [] });
    g.rules.push({ id: r.id, name: r.name, live: isLiveIncrease(r), lines: r.diffs.map(diffLine) });
  }
  const notes: string[] = [];
  if (s.already > 0) notes.push(`${plural(s.already, "rule")} already set — left alone`);
  for (const x of s.skipped) notes.push(`Skipped “${x.name}”${x.account_name ? ` (${x.account_name})` : ""}: ${x.reason}`);
  return {
    headline: `${plural(s.rules.length, "rule")} · ${plural(groups.length, "model")}`,
    changes: changeLines(s.changes),
    groups,
    notes,
  };
}

/** The apply POST's body: the card's rules (id + version) and the change spec. */
export function editApplyBody(accountId: string, s: MassEditSlots) {
  return { account_id: accountId, rules: s.rules.map((r) => ({ id: r.id, version: r.version })), changes: s.changes };
}

/** The apply 200, read defensively: one result per planned rule (a missing one reads as not changed). */
export function editResultsOf(resp: unknown, s: MassEditSlots): EditResult[] {
  const raw = resp && typeof resp === "object" && Array.isArray((resp as { results?: unknown }).results)
    ? (resp as { results: unknown[] }).results : [];
  const by = new Map<number, EditResult>();
  for (const x of raw) {
    if (!x || typeof x !== "object") continue;
    const r = x as { id?: unknown; ok?: unknown; reason?: unknown };
    if (typeof r.id === "number") by.set(r.id, { id: r.id, ok: r.ok === true, ...(typeof r.reason === "string" ? { reason: r.reason } : {}) });
  }
  return s.rules.map((r) => by.get(r.id) ?? { id: r.id, ok: false, reason: "no answer from the server" });
}

/** The result list: "✓ Morning mass · Model A" or "Morning mass · Model A — changed since you saw it". */
export function resultLines(results: EditResult[], s: MassEditSlots): Array<{ id: number; ok: boolean; text: string }> {
  const rule = new Map(s.rules.map((r) => [r.id, r]));
  return results.map((x) => {
    const r = rule.get(x.id);
    const who = r ? `${r.name} · ${r.account_name}` : `Rule ${x.id}`;
    return { id: x.id, ok: x.ok, text: x.ok ? `✓ ${who}` : `${who} — ${x.reason || "not changed"}` };
  });
}

/** "Changed 2 of 3 rules". */
export function resultHeadline(results: EditResult[]): string {
  const ok = results.filter((r) => r.ok).length;
  return `Changed ${ok} of ${plural(results.length, "rule")}`;
}

/** The draft's slots, read defensively (a missing field never crashes the card). */
export function editSlotsFrom(v: unknown): MassEditSlots | null {
  if (!v || typeof v !== "object") return null;
  const s = v as Partial<MassEditSlots>;
  const rules = Array.isArray(s.rules) ? s.rules.filter((r): r is EditRule =>
    !!r && typeof r === "object" && typeof r.id === "number" && typeof r.version === "string") : [];
  return {
    scope: s.scope === "all" ? "all" : "this",
    match: typeof s.match === "string" ? s.match : null,
    changes: s.changes && typeof s.changes === "object" ? s.changes : {},
    rules: rules.map((r) => ({ ...r, diffs: Array.isArray(r.diffs) ? r.diffs : [], name: String(r.name ?? ""),
      account_name: String(r.account_name ?? r.account_id ?? ""), is_enabled: r.is_enabled === true })),
    already: typeof s.already === "number" ? s.already : 0,
    skipped: Array.isArray(s.skipped) ? s.skipped : [],
  };
}
