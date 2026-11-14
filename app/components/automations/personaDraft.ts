/**
 * The persona block's (ModelInfoBlock, "Model info") form state: the textarea text, the text last known stored, and
 * the draft-from-images request (spec phase-03c › personaDraft.ts). A pure reducer (the block only dispatches) plus
 * `dirty`, `hasPersona`, `canDraft` and `requestBody`. With a persona in the box a click asks first (`confirm`), so
 * Cancel costs nothing; only `drafting` sends the request.
 */

/** account_config_api / _persona.MODEL_NOTES_MAX. */
export const MODEL_NOTES_MAX = 1000;

export type Phase = "idle" | "confirm" | "drafting" | "error";

export interface PersonaDraft {
  text: string;
  /** The text last read from or written to the server. */
  savedText: string;
  /** `confirm` = the replace question is open (no request yet); `drafting` = POST /admin/full-ai/persona/draft is out. */
  phase: Phase;
  error: string | null;
  /** Lines shown under the block: the route's `notes`, or the `need_describe` line.
   *  ASSUMPTION (rung 5): one additive field beside `error`, not a fifth phase. Overturned if notes need their own phase. */
  notes: string[];
}

/** POST /admin/full-ai/persona/draft's 200 (full_ai_api.py). */
export interface PersonaDraftResp {
  text: string;
  age: number | null;
  city: string | null;
  name: string;
  images_used: number;
  images_described: number;
  need_describe: boolean;
  notes: string[];
}

export type Action =
  | { type: "edit"; text: string }
  /** The Save PUT landed; `text` is what it sent (a newer edit typed meanwhile stays dirty).
   *  ASSUMPTION: the spec lists `saved` bare; it carries the sent text because the textarea stays editable while the
   *  PUT is out. Overturned if the block locks the textarea during Save. */
  | { type: "saved"; text: string }
  | { type: "serverText"; text: string }
  /** The "Make persona from the Creator's images" button. `template` = the server's `model_notes_template`. */
  | { type: "click"; template: string }
  /** The replace question's answer. */
  | { type: "confirm" }
  | { type: "cancel" }
  /** The draft landed: it replaces the text, unsaved (only Save writes). */
  | { type: "draftOk"; text: string; notes: string[] }
  /** The route had nothing to draft from (`need_describe`): the text stays, the note says what to run. */
  | { type: "draftEmpty"; note: string }
  | { type: "draftFail"; error: string };

export function personaDraftReducer(state: PersonaDraft, action: Action): PersonaDraft {
  switch (action.type) {
    case "edit":
      return { ...state, text: action.text };
    case "saved":
      return { ...state, savedText: action.text };
    case "serverText":
      return { ...state, text: action.text, savedText: action.text };
    case "click":
      if (!canDraft(state)) return state;
      return hasPersona(state.text, action.template) ? { ...state, phase: "confirm" } : startDrafting(state);
    case "confirm":
      return state.phase === "confirm" ? startDrafting(state) : state;
    case "cancel":
      return state.phase === "confirm" ? { ...state, phase: "idle", error: null } : state;
    case "draftOk":
      return state.phase === "drafting" ? { ...state, text: action.text, phase: "idle", notes: action.notes } : state;
    case "draftEmpty":
      return state.phase === "drafting" ? { ...state, phase: "idle", notes: [action.note] } : state;
    case "draftFail":
      return state.phase === "drafting" ? { ...state, phase: "error", error: action.error } : state;
  }
}

const startDrafting = (state: PersonaDraft): PersonaDraft => ({ ...state, phase: "drafting", error: null, notes: [] });

export const initPersonaDraft = (text: string): PersonaDraft =>
  personaDraftReducer({ text: "", savedText: "", phase: "idle", error: null, notes: [] }, { type: "serverText", text });

/** Shown while the request is out: the route may describe her photos before drafting (ticket 54). */
export const BUSY_LINE = "Describing up to 6 photos, then drafting…";
export const busyLine = (state: PersonaDraft): string | null => (state.phase === "drafting" ? BUSY_LINE : null);

/** The button may be pressed: no request out (a double tap is one request) and no replace question open. */
export const canDraft = (state: PersonaDraft): boolean => state.phase !== "drafting" && state.phase !== "confirm";

/** The draft POST body: the textarea as it is now, saved or not (the route keeps its Won't-do line). */
export const requestBody = (state: PersonaDraft, accountId: string) => ({ account_id: accountId, current_text: state.text });

export const dirty = (state: PersonaDraft): boolean => state.text !== state.savedText;

/** Save's PUT body: the STORED brain back with only `model_notes` changed (the PUT replaces the whole brain). */
export const buildPayload = <C extends object>(config: C, state: PersonaDraft): C & { model_notes: string } =>
  ({ ...config, model_notes: state.text });

// Python str.splitlines' line boundaries, so a line counts here exactly as it does on the server.
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;

/**
 * True when `text` holds anything beyond the blank template: mirrors `_persona._model_notes_block`, which keeps a
 * line unless it is blank or one of the template's label lines left empty ("Age:"), over the first MODEL_NOTES_MAX
 * chars. The blank label lines come from `template` (the server's `model_notes_template`).
 */
export function hasPersona(text: string, template: string): boolean {
  const blank = new Set(template.split(LINE_BREAK).map((ln) => ln.trim().toLowerCase()).filter(Boolean));
  // UTF-16 vs Python code-point slicing can't change the answer: any line holding an emoji before the cut is kept anyway.
  return text.slice(0, MODEL_NOTES_MAX).split(LINE_BREAK).some((ln) => {
    const t = ln.trim();
    return t !== "" && !blank.has(t.toLowerCase());
  });
}
