import type { FanId } from "@/lib/fanId";
import type { OFMessage } from "@/lib/relay";
import type { SendFailure } from "@/lib/sendFailure";

export function toUtcIso(raw: string | undefined): string {
  if (!raw) return new Date().toISOString();
  const s = raw.trim();
  // Relay live rows carry zone-less UTC; new Date() would read it as the viewer's local time.
  const hasZone = /[zZ]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s);
  const candidate = hasZone
    ? s
    : `${s.replace(" ", "T").replace(/(\.\d{3})\d+$/, "$1")}Z`;
  const d = new Date(candidate);
  return Number.isNaN(d.getTime()) ? s : d.toISOString();
}

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

export function appendMsg(prev: OFMessage[], msg: OFMessage): OFMessage[] {
  return hasId(prev, msg) ? prev : [...prev, msg];
}

export function insertMsg(prev: OFMessage[], msg: OFMessage): OFMessage[] {
  return hasId(prev, msg) ? prev : insertByCreatedAt(prev, msg);
}

function hasId(prev: OFMessage[], msg: OFMessage): boolean {
  const incoming = String(msg.id);
  return prev.some((m) => String(m.id) === incoming);
}

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

export function failMsg(prev: OFMessage[], tempId: number, failure?: SendFailure): OFMessage[] {
  return prev.map((m) =>
    m._tempId === tempId
      ? {
          ...m,
          _failed: true,
          _pending: false,
          _failedReason: failure?.reason,
          _failedMediaIds: failure?.refusedMediaIds,
          _failedUncertain: failure?.uncertain,
          _failedPaused: failure?.paused,
        }
      : m,
  );
}

export function dropMsg(prev: OFMessage[], tempId: number): OFMessage[] {
  return prev.filter((m) => m._tempId !== tempId);
}

export function evictMessage(list: OFMessage[], id: FanId): OFMessage[] {
  const gone = String(id);
  const out = list.filter((m) => String(m.id) !== gone);
  return out.length === list.length ? list : out;
}

const TOMBSTONES_MAX = 500;
const tombstones = new Map<string, Set<string>>();

export function tombstoneMessage(accountId: string, id: FanId): void {
  let set = tombstones.get(accountId);
  if (!set) { set = new Set(); tombstones.set(accountId, set); }
  set.delete(String(id));
  set.add(String(id));
  if (set.size > TOMBSTONES_MAX) set.delete(set.values().next().value!);
}

export function dropTombstoned(accountId: string | null, list: OFMessage[]): OFMessage[] {
  const set = accountId == null ? undefined : tombstones.get(accountId);
  if (!set?.size) return list;
  const out = list.filter((m) => !set.has(String(m.id)));
  return out.length === list.length ? list : out;
}

// OF's CDN takes ~2-3s to populate file urls, so the server reply often has media with no playable urls.
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

export const THREAD_KEEP = 90;

// Kept rows are the contiguous newest tail so paging older from the cache minimum crosses no gap.
export function trimThread(list: OFMessage[], keep: number): OFMessage[] {
  const optimistic = (m: OFMessage) => !(Number(m.id) > 0);
  let real = 0;
  let cut = -1;
  for (let i = list.length - 1; i >= 0; i--) {
    if (optimistic(list[i])) continue;
    if (++real > keep) { cut = i; break; }
  }
  if (cut < 0) return list;
  return list.filter((m, i) => i > cut || optimistic(m));
}
