/**
 * Custom redirect links' Create form: Name, Target URL, "Bot check before
 * redirect" and the form's error. A pure reducer (CustomRedirects only
 * dispatches), `normalizeTarget` (the relay's `_normalize_target` mirror) and
 * `formError` / `buildPayload`.
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

// "javascript:", "data:", "mailto:" … — a scheme with no "//". "host:8080" is not one (a digit follows).
const BARE_SCHEME = /^[a-z][a-z0-9+.-]*:(?!\d)/i;

/** The http(s) URL the relay stores, or null. No scheme → `https://` prepended
 *  (`ofl.ink/nora` → `https://ofl.ink/nora`); other schemes and hosts
 *  with no dot are refused. Mirror of service/tracking_links_api.py `_normalize_target`. */
export function normalizeTarget(raw: string): string | null {
  let url = raw.trim();
  if (!url || url.length > 2000 || /\s/.test(url)) return null;
  if (url.startsWith("//")) url = `https:${url}`;
  else if (!url.includes("://")) {
    if (BARE_SCHEME.test(url)) return null;
    url = `https://${url}`;
  }
  let u: URL;
  try { u = new URL(url); } catch { return null; }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  if (!u.hostname.replace(/^\.+|\.+$/g, "").includes(".")) return null;
  return url.length <= 2000 ? url : null;
}

/** What blocks Create, or null. */
export function formError(f: RedirectForm): string | null {
  if (!f.name.trim()) return "Name is required.";
  if (normalizeTarget(f.target) === null) return "Target must be a web address, e.g. ofl.ink/name.";
  return null;
}

/** The create body, or null while `formError` blocks it. Bot check is sent only
 *  when the server can run it (`available`). */
export function buildPayload(f: RedirectForm, available: boolean):
  { name: string; target_url: string; bot_check: boolean } | null {
  const target = normalizeTarget(f.target);
  if (formError(f) || target === null) return null;
  return { name: f.name.trim(), target_url: target, bot_check: available && f.botCheck };
}
