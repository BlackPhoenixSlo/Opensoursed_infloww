/**
 * Custom redirect links' Create form: Name, Target URL, "Bot check before
 * redirect" and the form's error. A pure reducer (RedirectLinksPanel only
 * dispatches) and `formError` / `buildPayload`. The relay alone decides what
 * a valid target is (service/tracking_links_api.py `_normalize_target`).
 */

export interface RedirectForm {
  name: string;
  target: string;
  botCheck: boolean;
  err: string | null;
}

export type Action =
  | { type: "edit"; field: "name" | "target"; value: string }
  | { type: "setBotCheck"; on: boolean }
  | { type: "fail"; err: string }
  | { type: "reset" };

export const INITIAL_FORM: RedirectForm = { name: "", target: "", botCheck: false, err: null };

export function redirectFormReducer(state: RedirectForm, action: Action): RedirectForm {
  switch (action.type) {
    case "edit":
      return { ...state, [action.field]: action.value, err: null };
    case "setBotCheck":
      return { ...state, botCheck: action.on };
    case "fail":
      return { ...state, err: action.err };
    case "reset":
      return INITIAL_FORM;
  }
}

/** What blocks Create, or null. The target's shape is the relay's call
 *  (`_normalize_target`): its 422 detail is shown as the form's error. */
export function formError(f: RedirectForm): string | null {
  if (!f.name.trim()) return "Name is required.";
  if (!f.target.trim()) return "Target URL is required.";
  return null;
}

/** The create body, as typed (the relay normalizes the target). Bot check is
 *  sent only when the server can run it (`available`). */
export function buildPayload(f: RedirectForm, available: boolean):
  { name: string; target_url: string; bot_check: boolean } {
  return { name: f.name.trim(), target_url: f.target.trim(), bot_check: available && f.botCheck };
}
