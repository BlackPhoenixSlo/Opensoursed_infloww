import { JEV_KEYS, type JevKey, type JevPicks } from "@/components/vault/jevPicks";

export interface EditorFields {
  desc: string;
  tags: string;
  tier: string;
  cap: string;
  script: string;
  price: string;
}
export type EditorField = keyof EditorFields;

export const WIRE_KEY: Record<EditorField, string> = {
  desc: "description",
  tags: "tags",
  tier: "explicitness_tier",
  cap: "suggested_caption",
  script: "suggested_script",
  price: "suggested_price_cents",
};
const FIELDS = Object.keys(WIRE_KEY) as EditorField[];

export interface EditorState {
  draft: EditorFields;
  base: EditorFields;
  pending: Partial<EditorFields> | null;
  jev: JevPicks;
  jevBase: JevPicks;
  pendingJev: JevPatch | null;
  saved: string[] | null;
  err: string;
  locked: ReadonlySet<string>;
}

export type JevPatch = Partial<Record<JevKey, string | null>>;

export type EditorAction =
  | { type: "edit"; field: EditorField; value: string }
  | { type: "pick"; key: JevKey; value: string | null }
  | { type: "refresh"; fields: EditorFields; picks?: JevPicks }
  | { type: "saveStart" }
  | { type: "saveOk"; locked: readonly string[] }
  | { type: "saveFail"; msg: string };

export function fieldsFromAi(ai: Record<string, unknown>): EditorFields {
  const priceCents = ai.suggested_price_cents;
  return {
    desc: (ai.description || ai.video_description || "") as string,
    tags: ((ai.tags as string[] | undefined) ?? []).join(", "),
    tier: (ai.explicitness_tier as string | undefined) ?? "",
    cap: (ai.suggested_caption as string | undefined) ?? "",
    script: (ai.suggested_script as string | undefined) ?? "",
    price: typeof priceCents === "number" ? (priceCents / 100).toFixed(2) : "",
  };
}

export function initialEditorState(fields: EditorFields, picks: JevPicks = {}): EditorState {
  return {
    draft: fields, base: fields, pending: null, jev: picks, jevBase: picks, pendingJev: null,
    saved: null, err: "", locked: new Set(),
  };
}

export function parsePriceCents(raw: string): number | null | undefined {
  const t = raw.trim();
  if (t === "") return null;
  const digits = t.replace(/[^0-9.]/g, "");
  if (digits === "") return undefined;
  const n = Number(digits);
  return Number.isFinite(n) ? Math.round(n * 100) : undefined;
}

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

export function jevPatch(state: EditorState): JevPatch {
  const out: JevPatch = {};
  for (const k of JEV_KEYS) {
    if (state.jev[k] !== state.jevBase[k]) out[k] = state.jev[k] ?? null;
  }
  return out;
}

// Only edited fields are sent, so only those lock (picks never lock a field).
export function buildPatch(state: EditorState): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const [f, v] of Object.entries(sendable(state)) as [EditorField, string][]) {
    patch[WIRE_KEY[f]] = f === "price" ? parsePriceCents(v) : v;
  }
  const jev = jevPatch(state);
  if (Object.keys(jev).length) patch.jev = jev;
  return patch;
}

export function isDirty(state: EditorState): boolean {
  return Object.keys(sendable(state)).length > 0 || Object.keys(jevPatch(state)).length > 0;
}

function withPatch(picks: JevPicks, patch: JevPatch): JevPicks {
  const out = { ...picks };
  for (const [k, v] of Object.entries(patch) as [JevKey, string | null][]) {
    if (v === null) delete out[k];
    else out[k] = v;
  }
  return out;
}

export function canSave(state: EditorState): boolean {
  return state.pending === null && isDirty(state);
}

export function vaultItemEditorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "edit":
      return { ...state, draft: { ...state.draft, [action.field]: action.value } };
    case "pick":
      return { ...state, jev: withPatch(state.jev, { [action.key]: action.value }) };
    // An untouched field follows the new `_ai` value, an edited one stays: a baseline recomputed per render made Re-describe get written back and locked.
    case "refresh": {
      const draft = { ...state.draft };
      const base = { ...state.base };
      let moved = false;
      for (const f of FIELDS) {
        if (state.draft[f] !== state.base[f] || base[f] === action.fields[f]) continue;
        draft[f] = base[f] = action.fields[f];
        moved = true;
      }
      let { jev, jevBase } = state;
      if (action.picks) {
        const follow: JevPatch = {};
        for (const k of JEV_KEYS) {
          if (state.jev[k] !== state.jevBase[k] || state.jevBase[k] === action.picks[k]) continue;
          follow[k] = action.picks[k] ?? null;
        }
        if (Object.keys(follow).length) {
          jev = withPatch(jev, follow);
          jevBase = withPatch(jevBase, follow);
          moved = true;
        }
      }
      return moved ? { ...state, draft, base, jev, jevBase } : state;
    }
    case "saveStart":
      if (!canSave(state)) return state;
      return { ...state, pending: sendable(state), pendingJev: jevPatch(state), saved: null, err: "" };
    case "saveOk": {
      if (!state.pending) return state;
      const sent = Object.keys(state.pending) as EditorField[];
      const picked = Object.keys(state.pendingJev ?? {}).length > 0;
      return {
        ...state,
        base: { ...state.base, ...state.pending },
        jevBase: withPatch(state.jevBase, state.pendingJev ?? {}),
        pending: null,
        pendingJev: null,
        saved: [...sent.map((f) => WIRE_KEY[f]), ...(picked ? ["jev"] : [])],
        locked: new Set(action.locked),
      };
    }
    case "saveFail":
      return { ...state, pending: null, pendingJev: null, err: action.msg };
  }
}
