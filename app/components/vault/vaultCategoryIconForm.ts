/**
 * The Folder icon dialog's form: the chosen image, its local preview URL, the square crop's focus (x / y, percent),
 * whether the preview loaded, the save in flight and the error line. A pure reducer (`VaultCategoryIconDialog` only
 * dispatches), `canSubmit` (Save / Use default) and `buildPayload` (the upload's fields).
 *
 * Choosing a file always starts over: crop centred, not ready until the preview loads. A file over 8 MB is refused
 * with no file, no preview and the crop reset (the old dialog kept the previous file's crop).
 */

export const MAX_ICON_BYTES = 8 * 1024 * 1024;
export const TOO_BIG = "Choose an image below 8 MB.";
export const BAD_IMAGE = "Choose a valid JPG, PNG or WebP image.";

export interface IconForm {
  file?: File;
  /** Object URL of `file` (the component creates and revokes it), "" when none. */
  preview: string;
  x: number;
  y: number;
  ready: boolean;
  busy: boolean;
  error: string;
}

export type Action =
  | { type: "choose"; file?: File; preview: string }
  | { type: "loaded" }
  | { type: "loadFailed" }
  | { type: "move"; axis: "x" | "y"; value: number }
  | { type: "submit" }
  | { type: "failed"; error: string }
  | { type: "done" };

export const INITIAL_ICON_FORM: IconForm = { preview: "", x: 50, y: 50, ready: false, busy: false, error: "" };

export const tooBig = (file?: File) => !!file && file.size > MAX_ICON_BYTES;

export function iconFormReducer(state: IconForm, action: Action): IconForm {
  switch (action.type) {
    case "choose":
      return tooBig(action.file)
        ? { ...INITIAL_ICON_FORM, error: TOO_BIG }
        : { ...INITIAL_ICON_FORM, file: action.file, preview: action.file ? action.preview : "" };
    case "loaded":
      return { ...state, ready: true };
    case "loadFailed":
      return { ...state, ready: false, error: BAD_IMAGE };
    case "move":
      return { ...state, [action.axis]: action.value };
    case "submit":
      return { ...state, busy: true, error: "" };
    case "failed":
      return { ...state, busy: false, error: action.error };
    case "done":
      return { ...state, busy: false };
  }
}

/** Save needs a loaded image; Use default (`reset`) only needs no save in flight. */
export const canSubmit = (s: IconForm, reset = false) => !s.busy && (reset || (!!s.file && s.ready));

/** The upload's fields: the file and the crop focus as fractions (0–1). */
export function buildPayload(s: IconForm): { file: File; x: number; y: number } | null {
  return s.file ? { file: s.file, x: s.x / 100, y: s.y / 100 } : null;
}
