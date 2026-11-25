export const MODEL_NOTES_MAX = 1000;

export type Phase = "idle" | "confirm" | "drafting" | "error";

export interface PersonaDraft {
  text: string;
  savedText: string;
  phase: Phase;
  error: string | null;
  notes: string[];
}

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
  | { type: "saved"; text: string }
  | { type: "serverText"; text: string }
  | { type: "click"; template: string }
  | { type: "confirm" }
  | { type: "cancel" }
  | { type: "draftOk"; text: string; notes: string[] }
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

export const BUSY_LINE = "Describing up to 6 photos, then drafting…";
export const busyLine = (state: PersonaDraft): string | null => (state.phase === "drafting" ? BUSY_LINE : null);

export const canDraft = (state: PersonaDraft): boolean => state.phase !== "drafting" && state.phase !== "confirm";

export const requestBody = (state: PersonaDraft, accountId: string) => ({ account_id: accountId, current_text: state.text });

export const dirty = (state: PersonaDraft): boolean => state.text !== state.savedText;

// The config PUT replaces the whole brain: send the stored config back with only model_notes changed.
export const buildPayload = <C extends object>(config: C, state: PersonaDraft): C & { model_notes: string } =>
  ({ ...config, model_notes: state.text });

// Python str.splitlines' boundaries, so a line counts here as it does on the server.
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;

export function hasPersona(text: string, template: string): boolean {
  const blank = new Set(template.split(LINE_BREAK).map((ln) => ln.trim().toLowerCase()).filter(Boolean));
  return text.slice(0, MODEL_NOTES_MAX).split(LINE_BREAK).some((ln) => {
    const t = ln.trim();
    return t !== "" && !blank.has(t.toLowerCase());
  });
}
