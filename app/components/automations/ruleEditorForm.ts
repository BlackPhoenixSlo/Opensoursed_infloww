/**
 * ReadyMadeRuleEditor's one popup as a pure reducer: the rule's trigger fields, its ONE post / message (premadeRows
 * `Row`) and the Raw JSON escape hatch (lib/rawJsonReducer) — no nested composer dialog.
 *
 *   • Three views (`editorView`): `form` (the post fields inline), `raw` (the textarea), `legacy` (an older
 *     multi-item / timed payload, readyMadeContent `isLegacy`: a notice + Raw JSON only, never converted to rows).
 *   • `form`: the rows are the content once the user edits them (`rowsDirty`); until then the stored payload is
 *     saved as is, so opening and saving a rule never rewrites keys the form doesn't hold.
 *   • `toRaw` writes the edited rows into the buffer first; `toForm` re-seeds the rows from it (an unparseable
 *     buffer stays in raw, rawJsonReducer `close`).
 *   • `canSave` / `buildBody` are the Create / Save changes gate and its request.
 */

import {
  buildPayload, payloadToRows, rowsReducer, type Kind, type Row, type RowsAction,
} from "@/components/compose/premadeRows";
import { hasContent, isLegacy } from "@/components/automations/readyMadeContent";
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
  rows: Row[];
  /** The user changed the rows since they were seeded: they, not `raw.value`, are the content. */
  rowsDirty: boolean;
  /** The stored payload minus `dry_run` (the switch owns it) and the textarea. */
  raw: RawJsonState<Payload>;
}

export type Fields = Pick<RuleEditorState, "name" | "intervalValue" | "intervalUnit" | "enabled" | "dryRun">;

export type RuleEditorAction =
  | { type: "field"; patch: Partial<Fields> }
  | { type: "rows"; a: RowsAction }
  /** Raw JSON keystrokes (`edit`), a failed save (`fail`), a legacy rule's Edit in Raw JSON (`open`). */
  | { type: "raw"; a: RawJsonAction<Payload> }
  | { type: "toRaw" }
  | { type: "toForm" };

export type EditorView = "form" | "raw" | "legacy";

const raw = rawJsonReducer(PAYLOAD_RAW);

export function initRuleEditor(
  kind: Kind,
  editing: { name: string; every_seconds: number | null; is_enabled: boolean; payload: Payload } | null,
): RuleEditorState {
  const payload = withoutDryRun(editing?.payload);
  const { value, unit } = splitInterval(editing?.every_seconds ?? 24 * 3600);
  return {
    kind,
    name: editing?.name ?? "",
    intervalValue: value,
    intervalUnit: unit,
    enabled: editing?.is_enabled ?? true,
    dryRun: Boolean(editing?.payload?.dry_run),
    rows: payloadToRows(payload, kind),
    rowsDirty: false,
    raw: initialRawJson(payload),
  };
}

export function editorView(s: RuleEditorState): EditorView {
  if (s.raw.raw) return "raw";
  return !s.rowsDirty && isLegacy(s.raw.value, s.kind) ? "legacy" : "form";
}

/** What would be saved (minus `dry_run`); null = the form has no text or media. */
export function currentPayload(s: RuleEditorState): Payload | null {
  if (editorView(s) === "form" && s.rowsDirty) return buildPayload(s.rows, { kind: s.kind });
  return s.raw.value;
}

export function ruleEditorReducer(s: RuleEditorState, a: RuleEditorAction): RuleEditorState {
  switch (a.type) {
    case "field":
      return { ...s, ...a.patch };
    case "rows":
      return { ...s, rows: rowsReducer(s.rows, a.a), rowsDirty: true };
    case "raw":
      return { ...s, raw: raw(s.raw, a.a) };
    case "toRaw": {
      if (s.raw.raw) return s;
      const value = currentPayload(s) ?? {};
      return { ...s, rowsDirty: false, raw: raw(raw(s.raw, { type: "set", value }), { type: "open" }) };
    }
    case "toForm": {
      const next = raw(s.raw, { type: "close" });
      if (next.raw) return { ...s, raw: next }; // unparseable: stays in raw
      return { ...s, raw: next, rows: payloadToRows(next.value, s.kind), rowsDirty: false };
    }
  }
}

/** Create / Save changes is live: the buffer parses and there is a post / message. */
export function canSave(s: RuleEditorState): boolean {
  const p = currentPayload(s);
  return canSubmit(s.raw) && p !== null && hasContent(p, s.kind);
}

export function everySeconds(s: RuleEditorState): number {
  return Math.round(s.intervalValue * UNIT_S[s.intervalUnit]);
}

/** The create / update body; null when Save is off. A blank name keeps the stored one (or the server default). */
export function buildBody(s: RuleEditorState): {
  name: string | undefined; every_seconds: number; payload: Payload; is_enabled: boolean;
} | null {
  const p = currentPayload(s);
  if (!canSave(s) || !p) return null;
  return {
    name: s.name.trim() || undefined,
    every_seconds: everySeconds(s),
    payload: s.dryRun ? { ...p, dry_run: true } : p,
    is_enabled: s.enabled,
  };
}
