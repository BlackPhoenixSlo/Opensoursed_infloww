/**
 * The persona block's (ModelInfoBlock, "Model info") form state: the textarea text and the text last known stored.
 * A pure reducer (the block only dispatches) plus `dirty` and `hasPersona`. Phase / error and the draft-from-images
 * actions join later (spec phase-03c › personaDraft.ts); today the block needs only edit / saved / serverText.
 */

/** account_config_api / _persona.MODEL_NOTES_MAX. */
export const MODEL_NOTES_MAX = 1000;

export interface PersonaDraft {
  text: string;
  /** The text last read from or written to the server. */
  savedText: string;
}

export type Action =
  | { type: "edit"; text: string }
  /** The Save PUT landed; `text` is what it sent (a newer edit typed meanwhile stays dirty).
   *  ASSUMPTION: the spec lists `saved` bare; it carries the sent text because the textarea stays editable while the
   *  PUT is out. Overturned if the block locks the textarea during Save. */
  | { type: "saved"; text: string }
  | { type: "serverText"; text: string };

export function personaDraftReducer(state: PersonaDraft, action: Action): PersonaDraft {
  switch (action.type) {
    case "edit":
      return { ...state, text: action.text };
    case "saved":
      return { ...state, savedText: action.text };
    case "serverText":
      return { ...state, text: action.text, savedText: action.text };
  }
}

export const initPersonaDraft = (text: string): PersonaDraft =>
  personaDraftReducer({ text: "", savedText: "" }, { type: "serverText", text });

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
