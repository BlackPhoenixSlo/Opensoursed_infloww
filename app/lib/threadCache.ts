/**
 * threadCache — pure `(prev, ...) => next` writes over one chat's message
 * cache (`["messages", accountId, fanId]`, oldest→newest). useChatMessages'
 * optimistic-send callbacks and the live message handler only dispatch here.
 */

import type { OFMessage } from "@/lib/relay";
import type { SendFailure } from "@/lib/sendFailure";

/** Normalize a message timestamp to a UTC ISO string (…Z).
 *
 *  The relay emits live (`emit_live`) outbound rows — welcome / AI reply / mass
 *  / funnel — with the DB's tz-NAIVE wall clock (`"2026-06-14 09:36:17"`, already
 *  UTC but zone-less). `new Date()` parses that as the VIEWER's local time, which
 *  both skews the bubble's displayed time and corrupts the sort key. REST
 *  `/messages` rows already carry a zone, so the two paths disagreed: live
 *  funnel/mass bubbles rendered at the wrong time AND (see insertByCreatedAt)
 *  stuck out of order. Tag a zone-less value as UTC; pass through one already
 *  zoned. */
export function toUtcIso(raw: string | undefined): string {
  if (!raw) return new Date().toISOString();
  const s = raw.trim();
  const hasZone = /[zZ]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s);
  const candidate = hasZone
    ? s
    : `${s.replace(" ", "T").replace(/(\.\d{3})\d+$/, "$1")}Z`;
  const d = new Date(candidate);
  return Number.isNaN(d.getTime()) ? s : d.toISOString();
}

/** Insert `row` into a thread cache kept in created_at order, instead of
 *  blind-appending. The bug: a live message can enter the cache AFTER newer
 *  rows are already present (a re-run funnel, an out-of-order SSE replay), and a
 *  plain `[...prev, row]` then pins it to the BOTTOM as if it were newest. We
 *  scan from the tail — the overwhelmingly common case is a genuinely new
 *  message that belongs at the end, so that path stays O(1) — and splice the row
 *  in just after the last one that isn't strictly newer (`<=` keeps ties in
 *  arrival order). Timestamps are normalized for the compare so a zoned REST row
 *  and a zone-less live row sort consistently. */
export function insertByCreatedAt(list: OFMessage[], row: OFMessage): OFMessage[] {
  const t = Date.parse(toUtcIso(row.createdAt));
  if (Number.isNaN(t)) return [...list, row];
  let i = list.length;
  while (i > 0) {
    const prevT = Date.parse(toUtcIso(list[i - 1].createdAt));
    if (Number.isNaN(prevT) || prevT <= t) break;
    i--;
  }
  return i >= list.length
    ? [...list, row]
    : [...list.slice(0, i), row, ...list.slice(i)];
}

/** Append a message (optimistic send); the same `prev` if its id is already there. */
export function appendMsg(prev: OFMessage[], msg: OFMessage): OFMessage[] {
  return hasId(prev, msg) ? prev : [...prev, msg];
}

/** Insert a live message in created_at order (insertByCreatedAt); the same
 *  `prev` if its id is already there. */
export function insertMsg(prev: OFMessage[], msg: OFMessage): OFMessage[] {
  return hasId(prev, msg) ? prev : insertByCreatedAt(prev, msg);
}

function hasId(prev: OFMessage[], msg: OFMessage): boolean {
  const incoming = String(msg.id);
  return prev.some((m) => String(m.id) === incoming);
}

/** Replace the optimistic row `tempId` with the server's message.
 *
 *  SSE can echo the outbound message (real id) before this HTTP reconcile
 *  resolves. If that row already exists, stamping the same id onto the
 *  optimistic row would create two rows with the same React key. Instead,
 *  fold the optimistic media fallback onto the existing real row and drop the
 *  placeholder. */
export function reconcileMsg(prev: OFMessage[], tempId: number, serverMsg: OFMessage): OFMessage[] {
  const opt = prev.find((m) => m._tempId === tempId);
  const serverId = String(serverMsg.id);
  const existingReal = prev.find(
    (m) => m._tempId !== tempId && String(m.id) === serverId,
  );
  if (existingReal) {
    return prev
      .filter((m) => m._tempId !== tempId)
      .map((m) => (m === existingReal && opt ? mergeMedia(opt, m) : m));
  }
  return prev.map((m) => (m._tempId === tempId ? mergeMedia(m, serverMsg) : m));
}

/** Mark the optimistic row `tempId` failed (its Retry button shows). */
export function failMsg(prev: OFMessage[], tempId: number, failure?: SendFailure): OFMessage[] {
  return prev.map((m) =>
    m._tempId === tempId
      ? {
          ...m,
          _failed: true,
          _pending: false,
          _failedReason: failure?.reason,
          _failedMediaIds: failure?.refusedMediaIds,
        }
      : m,
  );
}

/** Remove the optimistic row `tempId` (before a retry, or a cancel). */
export function dropMsg(prev: OFMessage[], tempId: number): OFMessage[] {
  return prev.filter((m) => m._tempId !== tempId);
}

/** Merge optimistic media's `files` into a server response — OF's CDN
 *  takes ~2-3s to populate `files.{thumb,source}.url`, so the server
 *  response often comes back with media but no playable URLs. We swap
 *  the optimistic file urls in until the next refresh catches them. */
function mergeMedia(opt: OFMessage, server: OFMessage): OFMessage {
  if (!opt?.media?.length || !server?.media?.length) return { ...server, _pending: false, _tempId: opt._tempId };
  const byId = new Map<number, OFMessage["media"][number]>();
  for (const om of opt.media) if (typeof om.id === "number") byId.set(om.id, om);
  const mergedMedia = server.media.map((sm, i) => {
    if (sm.files?.thumb?.url || sm.files?.source?.url) return sm;
    const fallback =
      (typeof sm.id === "number" ? byId.get(sm.id) : undefined) || opt.media[i];
    return fallback?.files ? { ...sm, files: fallback.files } : sm;
  });
  return { ...server, media: mergedMedia, _pending: false, _tempId: opt._tempId };
}
