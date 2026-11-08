/**
 * A document load of a screen with a bundle (lib/screenBundle.ts) starts that bundle with the auth probe (AuthGate),
 * so it is the screen's first relay call, not its third wave: the Dashboard's waited for /auth/me, then the Applied
 * settings (its days), then its cards' mount (slop slow-connections jp: started 1154 ms, settled 1815 ms).
 *
 * The Dashboard's days need the Agency's report zone and week start, which the Applied settings answer only later:
 * the last answer this browser saw (`rememberDashboardEntry`, written by the Dashboard), else the browser's zone and
 * Monday (the settings' defaults). A wrong guess is one bundle nobody joins (another key): the cards start their own
 * as before. `grid: false` (the session's role hides the Per-model cards): no guess, nothing would join it.
 *
 * One guess (`bootScreen`), from three cookies, for both halves: the server's for the HTML's inline boot
 * (lib/inlineBoot.server.ts) and AuthGate's start: the saved entry (`ENTRY_COOKIE`), the browser's zone
 * (`TZ_COOKIE`, the root layout's boot script) and whether the saved inbox scope is one Creator (`SCOPE_COOKIE`:
 * Messages Pro on one Creator reads its own routes, no agency-wide inbox bundle).
 */
import { DEFAULT_PERIOD, isPeriod } from "@/components/home/dashboardControls";
import { periodWindow } from "@/lib/dateRange";
import type { Screen } from "@/lib/screenKey";
import type { WeekStart } from "@/lib/shifts";

export interface DashboardEntry {
  tz: string | null;
  weekStart: WeekStart;
  /** The Dashboard drew the Per-model cards (the bundle's reader). */
  grid: boolean;
}

/** The saved entry (`rememberDashboardEntry`). */
const ENTRY_COOKIE = "chatterly_entry";
/** The browser's IANA zone, written on every document load (app/layout.tsx): a null `tz` means it. */
export const TZ_COOKIE = "chatterly_tz";
/** Whether the saved inbox scope is one Creator (`rememberScope`): `model` or `all`. */
const SCOPE_COOKIE = "chatterly_scope";
const YEAR_S = 365 * 24 * 3600;

/** A cookie's decoded value by name (the Next jar's `.value`; `cookieValue` over `document.cookie`); undefined: none. */
export type CookieRead = (name: string) => string | undefined;

/** The screen a document load of `pathAndSearch` opens and starts the bundle of, from its cookies (`cookie`); null:
 *  none. Messages Pro: its inbox, unless one Creator is in scope (the page opens no inbox screen). The Dashboard: its
 *  days per the saved entry's zone, else the browser's; with neither (the first document load on this browser), one
 *  Intl does not know (a junk cookie) or no Per-model cards (`grid: false`), no guess. Never throws. */
export function bootScreen(pathAndSearch: string, cookie: CookieRead): Screen | null {
  const u = new URL(pathAndSearch, "http://x");
  if (u.pathname === "/messages-pro") return cookie(SCOPE_COOKIE) === "model" ? null : { kind: "inbox", cursor: 0 };
  if (u.pathname !== "/") return null;
  const hint = parseDashboardEntry(cookie(ENTRY_COOKIE));
  const tz = hint?.tz ?? cookie(TZ_COOKIE);
  if (!tz || hint?.grid === false) return null;
  const w = u.searchParams.get("window");
  try {
    const [from, to] = periodWindow(w && isPeriod(w) ? w : DEFAULT_PERIOD, tz, hint?.weekStart ?? "monday");
    return { kind: "dashboard", from, to };
  } catch {
    return null;
  }
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

/** A saved entry (`raw`: its JSON); null: none or junk. */
function parseDashboardEntry(raw: string | null | undefined): DashboardEntry | null {
  try {
    const v = JSON.parse(raw ?? "null");
    return v && typeof v === "object" && (v.weekStart === "monday" || v.weekStart === "sunday")
      ? { tz: typeof v.tz === "string" ? v.tz : null, weekStart: v.weekStart, grid: v.grid !== false } : null;
  } catch {
    return null;
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

export function rememberDashboardEntry(e: DashboardEntry): void {
  writeCookie(ENTRY_COOKIE, JSON.stringify(e));
}
