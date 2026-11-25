export const SKEW_MS = 2 * 60_000;
export const LAG_MS = 5_000;

type Msg = { id?: unknown; fromUser?: { id?: unknown } | null; _tempId?: number; createdAt?: string | null };

export interface AskedEntry { firstAt: number; times: number }
export type Asked = Map<string, AskedEntry>;

// Relay never records OF-side sends; only outbound newer than the map counts, else every thread change re-fired a read.
export function attributionAsks(
  messages: readonly Msg[], ownerUserId: unknown, map: Record<string, unknown>, fetchedAt: number,
  asked: ReadonlyMap<string, AskedEntry>, now: number,
): { ask: string[]; recheckAt: number | null } {
  const ask: string[] = [];
  let recheckAt: number | null = null;
  for (const m of messages) {
    if (m.fromUser?.id !== ownerUserId || (m._tempId ?? 0) < 0) continue;
    const id = String(m.id ?? "");
    if (!/^\d+$/.test(id) || /^0+$/.test(id) || id in map) continue;
    const at = Date.parse(m.createdAt ?? "");
    if (!Number.isFinite(at) || at < fetchedAt - SKEW_MS) continue;
    const prev = asked.get(id);
    if (!prev) {
      ask.push(id);
      continue;
    }
    if (prev.times >= 2 || fetchedAt < prev.firstAt || fetchedAt >= at + LAG_MS) continue;
    if (now >= at + LAG_MS) ask.push(id);
    else recheckAt = Math.min(recheckAt ?? Infinity, at + LAG_MS);
  }
  return { ask, recheckAt };
}

export function noteAsks(asked: Asked, ids: readonly string[], now: number): void {
  for (const id of ids) {
    const prev = asked.get(id);
    asked.set(id, { firstAt: prev?.firstAt ?? now, times: (prev?.times ?? 0) + 1 });
  }
}
