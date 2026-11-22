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

/** One changed field, as the server words and judges it (assistant_edit._diff): the card only shows it. */
export interface EditDiff {
  field: EditField;
  label: string;
  /** The server's line (assistant_edit.diff_text) — the one wording, every prior value included. */
  text: string;
  /** The rule stays on and some message sends more (or charges differently) right away (rwl W30 S1). */
  live: boolean;
}

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
  /** The change spec in words (assistant_edit.change_lines) — the card's head, same as the summary's. */
  change_lines: string[];
  rules: EditRule[];
  /** Matching rules that already have the change. */
  already: number;
  skipped: Array<{ id: number; name: string; account_name?: string; reason: string }>;
}

/** One rule's apply outcome (the route's `results[]`). */
export interface EditResult { id: number; ok: boolean; reason?: string }

/** "Unsend after 8h → never" — the server's text (one formatter, rwl W30 F12). */
export const diffLine = (d: EditDiff) => d.text;

/** LIVE on the card: any diff the server judged live. */
export const isLive = (r: EditRule): boolean => r.diffs.some((d) => d.live);

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** Skips the card names; the rest are one count (the server's nothing-answer names 3 too). */
export const SKIPS_SHOWN = 3;

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
    g.rules.push({ id: r.id, name: r.name, live: isLive(r), lines: r.diffs.map(diffLine) });
  }
  const notes: string[] = [];
  if (s.already > 0) notes.push(`${plural(s.already, "rule")} already set — left alone`);
  // The first few skips by name, the rest counted (rwl W30 D1: a bulk edit's skips used to list every rule).
  for (const x of s.skipped.slice(0, SKIPS_SHOWN)) {
    notes.push(`Skipped “${x.name}”${x.account_name ? ` (${x.account_name})` : ""}: ${x.reason}`);
  }
  if (s.skipped.length > SKIPS_SHOWN) notes.push(`${plural(s.skipped.length - SKIPS_SHOWN, "more rule")} skipped`);
  return {
    headline: `${plural(s.rules.length, "rule")} · ${plural(groups.length, "model")}`,
    changes: s.change_lines,
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

const FIELDS: Readonly<Record<EditField, true>> = {
  unsend_after_hours: true, online_only: true, every_seconds: true, exclude_last_chat_hours: true, price: true,
  media_count: true, is_enabled: true,
};

/** A rule's diffs, read defensively: one without the server's text is dropped (never a guessed line). */
function diffsOf(v: unknown): EditDiff[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((x) => {
    const d = x && typeof x === "object" ? x as Partial<Record<keyof EditDiff, unknown>> : null;
    return d && typeof d.field === "string" && typeof d.text === "string" && d.text
      && Object.prototype.hasOwnProperty.call(FIELDS, d.field)
      ? [{ field: d.field as EditField, label: String(d.label ?? ""), text: d.text, live: d.live === true }] : [];
  });
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
    change_lines: Array.isArray(s.change_lines) ? s.change_lines.filter((x): x is string => typeof x === "string") : [],
    rules: rules.map((r) => ({ ...r, diffs: diffsOf(r.diffs), name: String(r.name ?? ""),
      account_name: String(r.account_name ?? r.account_id ?? ""), is_enabled: r.is_enabled === true })),
    already: typeof s.already === "number" ? s.already : 0,
    skipped: Array.isArray(s.skipped) ? s.skipped : [],
  };
}
