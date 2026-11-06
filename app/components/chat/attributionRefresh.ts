/**
 * attributionRefresh.ts — when an open thread's "Sent by" map (useChatAttribution) is worth re-reading.
 *
 * A teammate's send from another machine lands in the thread before the map knows it: re-read then. But an outbound
 * message the relay never recorded (sent from OnlyFans itself, or before this Agency's relay) is never in the map,
 * and re-reading for it re-fired on every thread change (measured: attribution 3x per open). So only an outbound
 * message newer than the map (`fetchedAt` less a clock-skew margin) counts, and each id is asked about once.
 */

export const SKEW_MS = 2 * 60_000;

type Msg = { id?: unknown; fromUser?: { id?: unknown } | null; _tempId?: number; createdAt?: string | null };

/** The outbound ids to re-read the map for (empty: none); the caller adds them to `asked`. */
export function attributionAsks(
  messages: readonly Msg[], ownerUserId: unknown, map: Record<string, unknown>, fetchedAt: number,
  asked: ReadonlySet<string>,
): string[] {
  const out: string[] = [];
  for (const m of messages) {
    if (m.fromUser?.id !== ownerUserId || (m._tempId ?? 0) < 0) continue;
    const id = String(m.id ?? "");
    if (!/^\d+$/.test(id) || /^0+$/.test(id) || id in map || asked.has(id)) continue;
    const at = Date.parse(m.createdAt ?? "");
    if (!Number.isFinite(at) || at < fetchedAt - SKEW_MS) continue;
    out.push(id);
  }
  return out;
}
