/**
 * ReadyMadeRuleEditor's one popup as a pure reducer: the rule's trigger fields, its ONE post / message (premadeRows
 * `Row`) and the Raw JSON escape hatch (lib/rawJsonReducer) — no nested composer dialog.
 *
 *   • `derive` reads everything else off the state once per render: the view — `form` (the post fields inline),
 *     `raw` (the textarea), `legacy` (a payload the form can't hold losslessly, readyMadeContent `formHoldReason`:
 *     a notice + Raw JSON only, never converted to a row) — the payload Save would store, and why Save waits.
 *   • `form` only opens on a payload that round-trips through the row, so the row IS the content there;
 *     `raw.value` stays the last seeded / parsed payload the view is judged on.
 *   • `toRaw` writes the form's payload (its one item, audience and price included) into the buffer first; `toForm`
 *     re-seeds the row from it (an unparseable buffer stays in raw, rawJsonReducer `close`).
 *   • `canSave` / `buildBody` are the Create / Save changes gate and its request. Save sends back what the user
 *     didn't touch exactly as stored: the payload object (its `dry_run` included), the interval and the name.
 */

import { buildPayload, payloadToRow, rowReducer, type Row, type RowAction } from "@/components/compose/premadeRows";
import { sendAdvice, sendGap, type Kind, type SendGap } from "@/components/compose/payloadRules";
import { formHoldReason, samePayload, type FormHoldReason } from "@/components/automations/readyMadeContent";
import { UNIT_S, splitInterval, type Unit } from "@/components/automations/ruleInterval";
import { PAYLOAD_RAW, withoutDryRun, type Payload } from "@/lib/rulePayload";
import { canSubmit, initialRawJson, rawJsonReducer, type RawJsonAction, type RawJsonState } from "@/lib/rawJsonReducer";

export interface RuleEditorState {
  kind: Kind;
  name: string;
  intervalValue: number;
  intervalUnit: Unit;
  enabled: boolean;
  dryRun: boolean;
  /** The one post / message (form view). */
  row: Row;
  /** The last seeded / parsed payload minus `dry_run` (the switch owns it) and the textarea. */
  raw: RawJsonState<Payload>;
  /** The rule as opened (null = new): what an untouched Save sends back unchanged. */
  stored: { payload: Payload; seed: Pick<Fields, "name" | "intervalValue" | "intervalUnit" | "dryRun" | "enabled"> } | null;
}

export type Fields = Pick<RuleEditorState, "name" | "intervalValue" | "intervalUnit" | "enabled" | "dryRun">;

export type RuleEditorAction =
  | { type: "field"; patch: Partial<Fields> }
  | { type: "row"; a: RowAction }
  /** Raw JSON keystrokes (`edit`), a failed save (`fail`). */
  | { type: "raw"; a: RawJsonAction<Payload> }
  | { type: "toRaw" }
  | { type: "toForm" };

export type EditorView = "form" | "raw" | "legacy";

export interface Derived {
  view: EditorView;
  /** The legacy view's why; null in the other views. */
  hold: FormHoldReason | null;
  /** What Save would store (minus `dry_run`). */
  payload: Payload;
  /** Editing, and the payload's content is the stored one (minus `dry_run`): Save sends the stored object back. */
  sameAsStored: boolean;
  /** Why Create / Save changes waits (the parse error aside), payloadRules `sendGap`; null = it doesn't (or the
   *  stored payload is untouched and the rule doesn't go live). */
  wait: SendGap | null;
  /** A warning that doesn't block Save, payloadRules `sendAdvice`. */
  advice: "ppv" | null;
}

const raw = rawJsonReducer(PAYLOAD_RAW);

export function initRuleEditor(
  kind: Kind,
  editing: { name: string; every_seconds: number | null; is_enabled: boolean; payload: Payload } | null,
): RuleEditorState {
  const payload = withoutDryRun(editing?.payload);
  const { value, unit } = splitInterval(editing?.every_seconds ?? 24 * 3600);
  const seed = {
    name: editing?.name ?? "", intervalValue: value, intervalUnit: unit, dryRun: Boolean(editing?.payload?.dry_run),
    enabled: editing?.is_enabled ?? true,
  };
  return {
    kind,
    ...seed,
    row: payloadToRow(payload, kind),
    raw: initialRawJson(payload),
    stored: editing ? { payload: editing.payload ?? {}, seed } : null,
  };
}

/** The view, the payload and Save's gate, read once (one round trip). Every view judges the payload by the same
 *  rules (payloadRules `sendGap` / `sendAdvice`), except the stored payload untouched: saving it back changes nothing
 *  it sends, so it never blocks a rename, a new interval, turning Dry run on or disabling. A rule that goes live
 *  here (enabled and not Dry run now, not before: Dry run off or Enabled on) is judged like any payload. */
export function derive(s: RuleEditorState): Derived {
  const hold = s.raw.raw ? null : formHoldReason(s.raw.value, s.kind);
  const view: EditorView = s.raw.raw ? "raw" : hold ? "legacy" : "form";
  // Editing, the form's payload is the seeded one until the row changes (a stored empty list too, which opens as
  // the blank row: else a rename or disable would wait on content the user never removed).
  const rowIsSeed = !!s.stored && JSON.stringify(s.row) === JSON.stringify(payloadToRow(s.raw.value, s.kind));
  const payload = view === "form" && !rowIsSeed ? buildPayload(s.row, s.kind) : s.raw.value;
  const sameAsStored = !!s.stored && samePayload(payload, withoutDryRun(s.stored.payload));
  const live = (f: Pick<Fields, "enabled" | "dryRun">) => f.enabled && !f.dryRun;
  const goesLive = !!s.stored && !live(s.stored.seed) && live(s);
  const wait = sameAsStored && !goesLive ? null : sendGap(payload, s.kind);
  return { view, hold, payload, sameAsStored, wait, advice: sendAdvice(payload, s.kind) };
}

export function ruleEditorReducer(s: RuleEditorState, a: RuleEditorAction): RuleEditorState {
  switch (a.type) {
    case "field":
      return { ...s, ...a.patch };
    case "row":
      return { ...s, row: rowReducer(s.row, a.a) };
    case "raw":
      return { ...s, raw: raw(s.raw, a.a) };
    case "toRaw": {
      if (s.raw.raw) return s;
      const value = derive(s).payload;
      return { ...s, raw: raw(raw(s.raw, { type: "set", value }), { type: "open" }) };
    }
    case "toForm": {
      if (!s.raw.raw) return s; // already the form / the notice: nothing to re-seed
      const next = raw(s.raw, { type: "close" });
      if (next.raw) return { ...s, raw: next }; // unparseable: stays in raw
      return { ...s, raw: next, row: payloadToRow(next.value, s.kind) };
    }
  }
}

/** Create / Save changes is live: the buffer parses and the post / message would send. */
export function canSave(s: RuleEditorState, d: Derived = derive(s)): boolean {
  return canSubmit(s.raw) && d.wait === null;
}

export function everySeconds(s: RuleEditorState): number {
  return Math.round(s.intervalValue * UNIT_S[s.intervalUnit]);
}

/** The create / update body; null when Save is off. Untouched fields go back as stored: no `name` (the caller keeps
 *  the stored one; a blank name too), no `every_seconds` (the stored interval stays, even one the minutes / hours
 *  fields can't show), and the stored payload object itself when neither it nor Dry run changed. */
export function buildBody(s: RuleEditorState, d: Derived = derive(s)): {
  name: string | undefined; every_seconds: number | undefined; payload: Payload; is_enabled: boolean;
} | null {
  if (!canSave(s, d)) return null;
  const p = d.payload;
  const o = s.stored;
  const nameTouched = !o || s.name !== o.seed.name;
  const intervalTouched = !o || s.intervalValue !== o.seed.intervalValue || s.intervalUnit !== o.seed.intervalUnit;
  const payloadTouched = !o || s.dryRun !== o.seed.dryRun || !d.sameAsStored;
  return {
    name: nameTouched ? s.name.trim() || undefined : undefined,
    every_seconds: intervalTouched ? everySeconds(s) : undefined,
    payload: !payloadTouched && o ? o.payload : s.dryRun ? { ...p, dry_run: true } : p,
    is_enabled: s.enabled,
  };
}
