/**
 * format.ts — shared formatters for the stats surface.
 *
 * Lives outside `cn`/utils because these are tiny number/date primitives
 * that 3+ components share verbatim. Behavior matches the original
 * inline copies in PerModelKpiGrid / PerEmployeeTable.
 */

/** Cents → "$1.23" / "$1,234". `null` / `undefined` / `NaN` → "—". */
export function fmtCents(c: number | null | undefined): string {
  if (c == null || Number.isNaN(c)) return "—";
  const d = c / 100;
  return d >= 1000
    ? `$${d.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    : `$${d.toFixed(2)}`;
}

/** Same as fmtCents but renders 0 as "—" — matches the PerEmployeeTable
 *  "no data" convention where empty cells stay quiet. */
export function fmtCentsBlankZero(c: number | null | undefined): string {
  if (c == null || c === 0 || Number.isNaN(c)) return "—";
  return fmtCents(c);
}

/** Cents → a Fan's Total spend at a glance (docs/spec/phase-02-fan-list-pane.md,
 *  Rows): whole dollars, "$45" / "$9999", and above $9,999 shortened to "k"
 *  with at most one decimal, "$10k" / "$12.5k". */
export function fmtSpend(cents: number): string {
  const dollars = Math.round(cents / 100);
  return dollars > 9_999 ? `$${Math.round(dollars / 100) / 10}k` : `$${dollars}`;
}

export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString();
}

/** Seconds → "9:59", or "1:02:05" from an hour up. Absent / zero / negative → "" so a caller can render the
 *  pill only when there is a duration to show (`dur && …`, `dur || "▶"`).
 *
 *  This was three identical private copies — VaultPicker's `fmtDur`,
 *  VaultTile's `fmtDuration`, and a fourth written for the composer's
 *  overlong-video warning — before they were collapsed here. */
export function fmtDuration(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = String(Math.floor(sec % 60)).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** A reply wait: seconds → "45s", "3m 05s", "2h 07m"; null → "—" (Chatting statistics' Response time, Creator
 *  reports' Reply time, the Dashboard's Avg reply time). */
export function fmtReplyTime(sec: number | null): string {
  if (sec == null) return "—";
  const s = Math.round(sec);
  if (s < 60) return `${s}s`;
  const two = (n: number) => String(n).padStart(2, "0");
  if (s < 3600) return `${Math.floor(s / 60)}m ${two(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${two(Math.floor((s % 3600) / 60))}m`;
}

/** A figure's change against the window (or bucket) before, Infloww's growth (analytics-creator-reports#58): unsigned
 *  to two decimals with its direction; "0.00%" when flat, "-" with nothing before to compare with. */
export interface Growth { text: string; dir: "up" | "down" | null }
export function growthOf(cur: number, prev: number | null | undefined): Growth {
  if (prev == null || !(prev > 0)) return { text: "-", dir: null };
  if (cur === prev) return { text: "0.00%", dir: null };
  const g = (cur - prev) / prev;
  const text = Math.abs(g * 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%";
  return { text, dir: g > 0 ? "up" : "down" };
}

/** Past ISO timestamp → "12s ago" / "5 min ago" / "3 h ago" / "2 d ago".
 *  Absent / unparseable → `null` (render nothing); a FUTURE stamp → "soon".
 *
 *  Shared so the automation surfaces cannot each grow a private `timeAgo`. (The `${h}h ago` family in MoneyRail / NotificationBell
 *  / IngestHealthBanner is a DIFFERENT wording with a 30-day cutoff — deliberately
 *  left alone rather than silently restyled.) */
export function fmtAgo(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return null;
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 0) return "soon";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

/** A relay stamp as a Date: the relay writes `datetime.utcnow()` and sends it zone-less, so a date and time with no
 *  zone is read as UTC (not the browser's zone). A stamp with a zone, or a date alone, parses as is. Null when empty
 *  or unparseable. */
export function parseUtc(s: string | null | undefined): Date | null {
  if (!s) return null;
  const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(s);
  const d = new Date(naive ? `${s.replace(" ", "T")}Z` : s);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDateShort(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "HH:MM" in the user's locale — used for "data through 13:45" captions. */
export function fmtTimeOnly(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "7:02 pm": Infloww's and OF's clock time (numeric hour, lower-case am/pm). */
export function clockTime(d: Date): string {
  return CLOCK.format(d).toLowerCase();
}
// One formatter for every call: `toLocaleTimeString` with options builds a new
// Intl.DateTimeFormat each time, the top self-time frame of a Fan List render
// under a DM flood (measured). Same output.
const CLOCK = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });
