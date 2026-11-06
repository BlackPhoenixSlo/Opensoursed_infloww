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
 * The server makes the same guess for the HTML's inline boot (lib/inlineBoot.server.ts) from two cookies: the saved
 * entry (`ENTRY_COOKIE`, written with it) and the browser's zone (`TZ_COOKIE`, the root layout's boot script).
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

const KEY = "chatterly:dashboard-entry";
/** The saved entry's copy for the server (lib/inlineBoot.server.ts). */
export const ENTRY_COOKIE = "chatterly_entry";
/** The browser's IANA zone, written on every document load (app/layout.tsx): a null `tz` means it. */
export const TZ_COOKIE = "chatterly_tz";
const YEAR_S = 365 * 24 * 3600;
const GUESS: DashboardEntry = { tz: null, weekStart: "monday", grid: true };

/** The screen a document load of `pathname?search` opens and its bundle; null: none. */
export function entryScreen(pathname: string, search: string, hint: DashboardEntry | null): Screen | null {
  if (pathname === "/messages-pro") return { kind: "inbox" };
  if (pathname !== "/") return null;
  const h = hint ?? GUESS;
  if (!h.grid) return null;
  const w = new URLSearchParams(search).get("window");
  const [from, to] = periodWindow(w && isPeriod(w) ? w : DEFAULT_PERIOD, h.tz, h.weekStart);
  return { kind: "dashboard", from, to };
}

/** A saved entry (`raw`: its JSON); null: none or junk. */
export function parseDashboardEntry(raw: string | null | undefined): DashboardEntry | null {
  try {
    const v = JSON.parse(raw ?? "null");
    return v && typeof v === "object" && (v.weekStart === "monday" || v.weekStart === "sunday")
      ? { tz: typeof v.tz === "string" ? v.tz : null, weekStart: v.weekStart, grid: v.grid !== false } : null;
  } catch {
    return null;
  }
}

export function readDashboardEntry(): DashboardEntry | null {
  try {
    return parseDashboardEntry(window.localStorage.getItem(KEY));
  } catch {
    return null;
  }
}

export function rememberDashboardEntry(e: DashboardEntry): void {
  const v = JSON.stringify(e);
  try {
    window.localStorage.setItem(KEY, v);
  } catch { /* storage off: the next load guesses */ }
  try {
    document.cookie = `${ENTRY_COOKIE}=${encodeURIComponent(v)}; path=/; max-age=${YEAR_S}; samesite=lax`;
  } catch { /* cookies off: the server guesses no bundle */ }
}
