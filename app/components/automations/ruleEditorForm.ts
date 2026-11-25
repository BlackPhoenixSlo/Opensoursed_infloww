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
  row: Row;
  raw: RawJsonState<Payload>;
  stored: { payload: Payload; seed: Pick<Fields, "name" | "intervalValue" | "intervalUnit" | "dryRun" | "enabled"> } | null;
}

export type Fields = Pick<RuleEditorState, "name" | "intervalValue" | "intervalUnit" | "enabled" | "dryRun">;

export type RuleEditorAction =
  | { type: "field"; patch: Partial<Fields> }
  | { type: "row"; a: RowAction }
  | { type: "raw"; a: RawJsonAction<Payload> }
  | { type: "toRaw" }
  | { type: "toForm" };

export type EditorView = "form" | "raw" | "legacy";

export interface Derived {
  view: EditorView;
  hold: FormHoldReason | null;
  payload: Payload;
  sameAsStored: boolean;
  wait: SendGap | null;
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

export function derive(s: RuleEditorState): Derived {
  const hold = s.raw.raw ? null : formHoldReason(s.raw.value, s.kind);
  const view: EditorView = s.raw.raw ? "raw" : hold ? "legacy" : "form";
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
      if (!s.raw.raw) return s;
      const next = raw(s.raw, { type: "close" });
      if (next.raw) return { ...s, raw: next };
      return { ...s, raw: next, row: payloadToRow(next.value, s.kind) };
    }
  }
}

export function canSave(s: RuleEditorState, d: Derived = derive(s)): boolean {
  return canSubmit(s.raw) && d.wait === null;
}

export function everySeconds(s: RuleEditorState): number {
  return Math.round(s.intervalValue * UNIT_S[s.intervalUnit]);
}

// Untouched fields go back as stored (name, every_seconds, the payload object itself), even ones the form can't show.
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
