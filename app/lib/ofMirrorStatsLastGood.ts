export interface LastGood {
  data: unknown;
  at: number;
}

const DATES = ["start", "end", "startDate", "endDate"];
const MAX = 400;
// In memory only: a reload starts empty and an identity switch empties it (clearIdentityMemory).
const store = new Map<string, LastGood>();

export const selectionOf = (p: { key: string; startApi: string }): string => (p.key[0] === "m" ? `${p.key}@${p.startApi.slice(0, 7)}` : p.key);

export function lastGoodKey(accountId: string | null, period: string, route: string | null): string | null {
  if (!accountId || !route) return null;
  const [path, query = ""] = route.split("?");
  const q = new URLSearchParams(query);
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

export const forgetAll = (): void => store.clear();

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
