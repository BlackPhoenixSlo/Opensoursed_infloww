/**
 * attributionRefresh.ts — when an open thread's "Sent by" map (useChatAttribution) is worth re-reading.
 *
 * A teammate's send from another machine lands in the thread before the map knows it: re-read then. But an outbound
 * message the relay never recorded (sent from OnlyFans itself, or before this Agency's relay) is never in the map,
 * and re-reading for it re-fired on every thread change (measured: attribution 3x per open). So only an outbound
 * message newer than the map (`fetchedAt` less a clock-skew margin) counts, and each id is asked about at most
 * twice: once on sight, and once more only when that re-read landed within LAG_MS of the message (the relay may
 * not have written it yet), no sooner than LAG_MS after it.
 */

export const SKEW_MS = 2 * 60_000;
/** How long after a send the relay may still be writing its attribution. */
export const LAG_MS = 5_000;

type Msg = { id?: unknown; fromUser?: { id?: unknown } | null; _tempId?: number; createdAt?: string | null };

/** Per id: when it was first asked about, and how many times. */
export interface AskedEntry { firstAt: number; times: number }
export type Asked = Map<string, AskedEntry>;

/** The outbound ids to re-read the map for now (the caller records them with `noteAsks`), and when to look again
 *  for a second ask that isn't due yet (null: none). */
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
    // The second ask: only after the first re-read landed, and it landed too soon after the send.
    if (prev.times >= 2 || fetchedAt < prev.firstAt || fetchedAt >= at + LAG_MS) continue;
    if (now >= at + LAG_MS) ask.push(id);
    else recheckAt = Math.min(recheckAt ?? Infinity, at + LAG_MS);
  }
  return { ask, recheckAt };
}

/** Records the asks `attributionAsks` returned. */
export function noteAsks(asked: Asked, ids: readonly string[], now: number): void {
  for (const id of ids) {
    const prev = asked.get(id);
    asked.set(id, { firstAt: prev?.firstAt ?? now, times: (prev?.times ?? 0) + 1 });
  }
}
