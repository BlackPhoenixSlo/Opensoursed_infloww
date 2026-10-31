/**
 * vaultItemEditorReducer — VaultManagePanel's per-item editor (the details drawer).
 *
 *   draft  — what the inputs show (strings, as typed)
 *   base   — per field, the value the draft is compared against
 *   pending — the fields in flight to Save & lock (null = not saving)
 *
 *   • `refresh{fields}` (the open item's `_ai` changed under the editor:
 *     Re-describe, the post-save merge) moves an UNTOUCHED field — draft and
 *     base together — to the new value, and leaves an EDITED field alone, draft
 *     and base both. The old editor recomputed its baseline from the prop on
 *     every render while the inputs kept their own copy, so a Re-describe left
 *     the old text on screen, read every field the describe changed as an
 *     operator edit, and Save & lock wrote the OLD values back and locked them.
 *   • `saveOk` moves the base of exactly the fields that were sent to what was
 *     sent; the parent's merge (`refresh`) then shows the server's spelling.
 *   • `buildPatch` sends only edited fields. A price that parses to no number
 *     ("abc", "1.2.3") is not sent; blank clears it.
 */

/** The editor's fields, as the inputs hold them. */
export interface EditorFields {
  desc: string;
  tags: string;
  tier: string;
  cap: string;
  script: string;
  price: string;
  breasts: string;
  vulva: string;
  anus: string;
}
export type EditorField = keyof EditorFields;

/** The override+lock endpoint's key for each field (contract §6c). */
export const WIRE_KEY: Record<EditorField, string> = {
  desc: "description",
  tags: "tags",
  tier: "explicitness_tier",
  cap: "suggested_caption",
  script: "suggested_script",
  price: "suggested_price_cents",
  breasts: "breasts_vis",
  vulva: "vulva_vis",
  anus: "anus_vis",
};
const FIELDS = Object.keys(WIRE_KEY) as EditorField[];

export interface EditorState {
  draft: EditorFields;
  base: EditorFields;
  /** The edited fields a save sent, until it answers. */
  pending: Partial<EditorFields> | null;
  /** Wire keys of the last successful save. */
  saved: string[] | null;
  err: string;
  /** Wire keys the server reports locked. */
  locked: ReadonlySet<string>;
}

export type EditorAction =
  | { type: "edit"; field: EditorField; value: string }
  | { type: "refresh"; fields: EditorFields }
  | { type: "saveStart" }
  | { type: "saveOk"; locked: readonly string[] }
  | { type: "saveFail"; msg: string };

/** The editor's fields from an item's `_ai` read. */
export function fieldsFromAi(ai: Record<string, unknown>): EditorFields {
  const priceCents = ai.suggested_price_cents;
  return {
    desc: (ai.description || ai.video_description || "") as string,
    tags: ((ai.tags as string[] | undefined) ?? []).join(", "),
    tier: (ai.explicitness_tier as string | undefined) ?? "",
    cap: (ai.suggested_caption as string | undefined) ?? "",
    script: (ai.suggested_script as string | undefined) ?? "",
    price: typeof priceCents === "number" ? (priceCents / 100).toFixed(2) : "",
    // The exposure flags. They decide the folder, the price band and whether
    // an item may be mass-sent, so an operator who spots a wrong one while
    // editing a caption should be able to fix it here rather than hunting for
    // the review modal.
    breasts: (ai.breasts_vis as string | undefined) ?? "",
    vulva: (ai.vulva_vis as string | undefined) ?? "",
    anus: (ai.anus_vis as string | undefined) ?? "",
  };
}

export function initialEditorState(fields: EditorFields): EditorState {
  return { draft: fields, base: fields, pending: null, saved: null, err: "", locked: new Set() };
}

/** Dollars as typed → cents on the wire; `undefined` = not a number, not sent. */
export function parsePriceCents(raw: string): number | null | undefined {
  const t = raw.trim();
  if (t === "") return null;
  const digits = t.replace(/[^0-9.]/g, "");
  if (digits === "") return undefined;
  const n = Number(digits);
  return Number.isFinite(n) ? Math.round(n * 100) : undefined;
}

/** The edited fields a save would send (an unparseable price is left out). */
function sendable(state: EditorState): Partial<EditorFields> {
  const out: Partial<EditorFields> = {};
  for (const f of FIELDS) {
    const v = f === "price" ? state.draft.price.trim() : state.draft[f];
    if (v === state.base[f]) continue;
    if (f === "price" && parsePriceCents(v) === undefined) continue;
    out[f] = v;
  }
  return out;
}

/** The PATCH `fields` body: only edited fields, so only those lock. */
export function buildPatch(state: EditorState): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const [f, v] of Object.entries(sendable(state)) as [EditorField, string][]) {
    patch[WIRE_KEY[f]] = f === "price" ? parsePriceCents(v) : v;
  }
  return patch;
}

export function isDirty(state: EditorState): boolean {
  return Object.keys(sendable(state)).length > 0;
}

export function canSave(state: EditorState): boolean {
  return state.pending === null && isDirty(state);
}

export function vaultItemEditorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "edit":
      return { ...state, draft: { ...state.draft, [action.field]: action.value } };
    case "refresh": {
      const draft = { ...state.draft };
      const base = { ...state.base };
      let moved = false;
      for (const f of FIELDS) {
        if (state.draft[f] !== state.base[f] || base[f] === action.fields[f]) continue;
        draft[f] = base[f] = action.fields[f];
        moved = true;
      }
      return moved ? { ...state, draft, base } : state;
    }
    case "saveStart":
      if (!canSave(state)) return state;
      return { ...state, pending: sendable(state), saved: null, err: "" };
    case "saveOk": {
      if (!state.pending) return state;
      const sent = Object.keys(state.pending) as EditorField[];
      return {
        ...state,
        base: { ...state.base, ...state.pending },
        pending: null,
        saved: sent.map((f) => WIRE_KEY[f]),
        locked: new Set(action.locked),
      };
    }
    case "saveFail":
      return { ...state, pending: null, err: action.msg };
  }
}
