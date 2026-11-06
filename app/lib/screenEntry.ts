/**
 * A document load of a screen with a bundle (lib/screenBundle.ts) starts that bundle with the auth probe (AuthGate),
 * so it is the screen's first relay call, not its third wave: the Dashboard's waited for /auth/me, then the Applied
 * settings (its days), then its cards' mount (slop slow-connections jp: started 1154 ms, settled 1815 ms).
 *
 * The Dashboard's days need the Agency's report zone and week start, which the Applied settings answer only later:
 * the last answer this browser saw (`rememberDashboardEntry`, written by the Dashboard), else the browser's zone and
 * Monday (the settings' defaults). A wrong guess is one bundle nobody joins (another key): the cards start their own
 * as before. `grid: false` (the session's role hides the Per-model cards): no guess, nothing would join it.
 */
import { DEFAULT_PERIOD, isPeriod } from "@/components/home/dashboardControls";
import { periodWindow } from "@/lib/dateRange";
import type { Screen } from "@/lib/screenBundle";
import type { WeekStart } from "@/lib/shifts";

export interface DashboardEntry {
  tz: string | null;
  weekStart: WeekStart;
  /** The Dashboard drew the Per-model cards (the bundle's reader). */
  grid: boolean;
}

const KEY = "chatterly:dashboard-entry";
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

export function readDashboardEntry(): DashboardEntry | null {
  try {
    const v = JSON.parse(window.localStorage.getItem(KEY) ?? "null");
    return v && typeof v === "object" && (v.weekStart === "monday" || v.weekStart === "sunday")
      ? { tz: typeof v.tz === "string" ? v.tz : null, weekStart: v.weekStart, grid: v.grid !== false } : null;
  } catch {
    return null;
  }
}

export function rememberDashboardEntry(e: DashboardEntry): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(e));
  } catch { /* storage off: the next load guesses */ }
}
