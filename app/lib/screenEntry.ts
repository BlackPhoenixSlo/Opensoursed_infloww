/**
 * A document load of a screen with a bundle (lib/screenBundle.ts) starts that bundle with the auth probe (AuthGate),
 * so it is the screen's first relay call, not its third wave. Only Messages Pro's inbox boots so; the Dashboard does
 * not (its Per-model cards read the bundle after the Applied settings answer). An old saved Dashboard entry cookie
 * (`chatterly_entry`) is ignored.
 *
 * One guess (`bootScreen`), from the cookies, for both halves: the server's for the HTML's inline boot
 * (lib/inlineBoot.server.ts) and AuthGate's start: whether the saved inbox scope is one Creator (`SCOPE_COOKIE`:
 * Messages Pro on one Creator reads its own routes, no agency-wide inbox bundle).
 */
import type { Screen } from "@/lib/screenKey";

/** Whether the saved inbox scope is one Creator (`rememberScope`): `model` or `all`. */
const SCOPE_COOKIE = "chatterly_scope";
const YEAR_S = 365 * 24 * 3600;

/** A cookie's decoded value by name (the Next jar's `.value`; `cookieValue` over `document.cookie`); undefined: none. */
export type CookieRead = (name: string) => string | undefined;

/** The screen a document load of `pathAndSearch` opens and starts the bundle of, from its cookies (`cookie`); null:
 *  none. Messages Pro: its inbox, unless one Creator is in scope (the page opens no inbox screen). Any other route,
 *  the Dashboard included: none. Never throws. */
export function bootScreen(pathAndSearch: string, cookie: CookieRead): Screen | null {
  const u = new URL(pathAndSearch, "http://x");
  if (u.pathname === "/messages-pro") return cookie(SCOPE_COOKIE) === "model" ? null : { kind: "inbox", cursor: 0 };
  return null;
}

/** `name`'s decoded value in a Cookie header (`document.cookie`); undefined: none, or undecodable (as Next's jar). */
export function cookieValue(cookies: string, name: string): string | undefined {
  const hit = cookies.split("; ").find((c) => c.startsWith(`${name}=`));
  if (hit == null) return undefined;
  try {
    return decodeURIComponent(hit.slice(name.length + 1));
  } catch {
    return undefined;
  }
}

/** Set (null: expire) `name` for the next document load's guess. */
function writeCookie(name: string, value: string | null): void {
  try {
    document.cookie = `${name}=${encodeURIComponent(value ?? "")}; path=/; max-age=${value == null ? 0 : YEAR_S}; samesite=lax`;
  } catch { /* cookies off: the next document load guesses without it, as before */ }
}

/** Mirror whether the saved inbox scope is one Creator (`one`) for the next document load's guess. */
export function rememberScope(one: boolean): void {
  writeCookie(SCOPE_COOKIE, one ? "model" : "all");
}

/** Forget the mirrored scope: an identity switch (the next principal's scope is its own). */
export function forgetScope(): void {
  writeCookie(SCOPE_COOKIE, null);
}
