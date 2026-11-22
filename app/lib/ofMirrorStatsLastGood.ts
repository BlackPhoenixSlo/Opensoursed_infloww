/**
 * The last answer each Statistics read gave, per Creator, period and read (its route without the period's dates, which
 * move with the clock): what the page keeps showing, marked "as of", when a fresh read fails after its retries.
 * In memory only: a reload starts empty, an identity switch empties it (clearIdentityMemory), and a read that never
 * answered stays a dash.
 */

export interface LastGood {
  data: unknown;
  /** When that answer arrived (ms). */
  at: number;
}

const DATES = ["start", "end", "startDate", "endDate"];
const MAX = 400;
const store = new Map<string, LastGood>();

/** The period picked as a selection: a named month (`m0` "this month", …) with the month it names; others their key. */
export const selectionOf = (p: { key: string; startApi: string }): string => (p.key[0] === "m" ? `${p.key}@${p.startApi.slice(0, 7)}` : p.key);

/**
 * The read's identity across clock moves: the Creator, the period picked (selectionOf), the route minus its dates (bar
 * Activity Streak's month) and the first page's marker (Statements' first cursor is made from the clock; a later
 * page's is OF's own).
 */
export function lastGoodKey(accountId: string | null, period: string, route: string | null): string | null {
  if (!accountId || !route) return null;
  const [path, query = ""] = route.split("?");
  const q = new URLSearchParams(query);
  // Activity Streak reads a calendar month whatever the period: that month (its start's) names the read.
  if (path.endsWith("/streaks")) q.set("month", (q.get("start") ?? "").slice(0, 7));
  for (const d of DATES) q.delete(d);
  if (!Number(q.get("offset"))) q.delete("marker");
  q.sort();
  return `${accountId}|${period}|${path}?${q}`;
}

export function remember(key: string | null, data: unknown, at: number): void {
  if (!key || data === undefined) return;
  store.delete(key);
  store.set(key, { data, at });
  if (store.size > MAX) store.delete(store.keys().next().value!);
}

export const recall = (key: string | null): LastGood | undefined => (key ? store.get(key) : undefined);

/** Forget every answer (an identity switch: clearIdentityMemory; the tests). */
export const forgetAll = (): void => store.clear();

/**
 * What to draw for one read: nothing once refused (`permanent`: neither its own earlier data nor a remembered answer,
 * which is forgotten, until a read is let through again); else its own data while it has some (a failed re-read keeps
 * it), else the last good answer. `asOf`: when the data shown was read, only when the read failed.
 */
export function shownFor(key: string | null, r: { data: unknown; failed: boolean; at: number; permanent?: boolean }): { data: unknown; asOf: number | null } {
  if (!r.failed) {
    remember(key, r.data, r.at);
    return { data: r.data, asOf: null };
  }
  if (r.permanent) {
    if (key) store.delete(key);
    return { data: undefined, asOf: null };
  }
  if (r.data !== undefined) return { data: r.data, asOf: r.at };
  const last = recall(key);
  return last ? { data: last.data, asOf: last.at } : { data: undefined, asOf: null };
}
