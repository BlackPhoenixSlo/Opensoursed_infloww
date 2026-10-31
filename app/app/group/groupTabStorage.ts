/**
 * What one /group tab keeps across a reload, and what it reads at mount: the
 * slot list, its tab id, its createdAt and its last beat (sessionStorage, per
 * tab; a reload after the last beat went stale is reborn young), the seed
 * params (?add= / ?slots= / ?spawn=, consumed once), which live tabs it yields
 * a shared fan to (`olderTabs`), and the unresponded count it shows
 * (`countUnresponded`: a read of the React Query chats cache, never a fetch).
 */

import type { QueryClient } from "@tanstack/react-query";

import { GROUP_HEARTBEAT_TTL_MS, cleanSlots, parseSlotsParam, type GroupSlot } from "@/lib/groupChannel";
import { fanIdFromParam, sameUserId } from "@/lib/fanId";
import type { OFChatItem } from "@/lib/relay";

export const SLOTS_KEY = "chatterly:group-slots";
export const TAB_ID_KEY = "chatterly:group-tab-id";
export const CREATED_AT_KEY = "chatterly:group-tab-created-at";
export const LAST_BEAT_KEY = "chatterly:group-tab-last-beat";

/** The slots this tab held before a reload. Both fan id shapes: a
 *  `typeof fan !== "number"` check here dropped every Fansly slot on reload. */
export function readSlots(): GroupSlot[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(SLOTS_KEY);
    return raw ? cleanSlots(JSON.parse(raw) as unknown) : [];
  } catch {
    return [];
  }
}

export function writeSlots(slots: readonly GroupSlot[]): void {
  try {
    window.sessionStorage.setItem(SLOTS_KEY, JSON.stringify(slots));
  } catch {
    /* quota / safari private — accept the loss */
  }
}

export interface SeedParams {
  seeds: GroupSlot[];
  spawnToken: string | null;
  /** The URL without the seed params (path + search + hash), or null when
   *  it had none (a plain reload: nothing to strip). */
  rest: string | null;
}

/** Pure: the seed params of `href`.
 *    ?add=<acctId>:<fanId>              — one fan (👥 from a chat header)
 *    ?slots=<acctId>:<fanId>,...        — a whole list (money rail's last-8)
 *    ?spawn=<token>                     — pairs us with the source tab */
export function parseSeedParams(href: string): SeedParams {
  const url = new URL(href);
  const rawAdd = url.searchParams.get("add");
  const rawSlots = url.searchParams.get("slots");
  const spawnToken = url.searchParams.get("spawn");
  if (!rawAdd && !rawSlots && !spawnToken) return { seeds: [], spawnToken: null, rest: null };
  url.searchParams.delete("add");
  url.searchParams.delete("slots");
  url.searchParams.delete("spawn");
  const rest = url.pathname + (url.search ? url.search : "") + url.hash;
  if (rawSlots) return { seeds: parseSlotsParam(rawSlots), spawnToken, rest };
  if (!rawAdd) return { seeds: [], spawnToken, rest };
  const idx = rawAdd.lastIndexOf(":");
  if (idx <= 0) return { seeds: [], spawnToken, rest };
  const accountId = rawAdd.slice(0, idx);
  // Not `Number(...)`: a Fansly snowflake does not survive float64, so the
  // "👥 group" button opened a slot pointing at a fan that does not exist.
  const fan = fanIdFromParam(rawAdd.slice(idx + 1));
  if (!accountId || fan == null) return { seeds: [], spawnToken, rest };
  return { seeds: [{ accountId, fanId: fan }], spawnToken, rest };
}

/** Parse the seed params once and clear them from the URL (replaceState: not
 *  in history) so a refresh doesn't re-seed or re-claim. `fresh`: the URL had
 *  seed params, i.e. this tab was just opened by a source tab. */
export function takeSeedParams(): { seeds: GroupSlot[]; spawnToken: string | null; fresh: boolean } {
  if (typeof window === "undefined") return { seeds: [], spawnToken: null, fresh: false };
  const { seeds, spawnToken, rest } = parseSeedParams(window.location.href);
  if (rest === null) return { seeds, spawnToken, fresh: false };
  window.history.replaceState({}, "", rest);
  return { seeds, spawnToken, fresh: true };
}

function genId(): string {
  return window.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Stable per-tab id. Re-uses an existing one from sessionStorage so a
 *  refresh doesn't rotate identity (which would orphan the registry
 *  entry for TTL before scanners cleaned up). `fresh` (seed params: a
 *  just-opened tab) mints a new one even over a stored id: some browsers copy
 *  sessionStorage into a window.open'd child, which would otherwise share its
 *  opener's id (one registry entry, and every add addressed to both). */
export function resolveTabId(fresh: boolean): string {
  if (typeof window === "undefined") return "";
  try {
    const existing = window.sessionStorage.getItem(TAB_ID_KEY);
    if (existing && !fresh) return existing;
    const id = genId();
    window.sessionStorage.setItem(TAB_ID_KEY, id);
    return id;
  } catch {
    return genId();
  }
}

/** When this tab first registered: the older-wins tiebreak (`olderTabs`).
 *  Kept per tab in sessionStorage, so a reload stays as old as the tab (a
 *  reload stamped now made a reloaded tab yield its fans to a younger one).
 *  `fresh` stamps `now` even over a stored value, as `resolveTabId` mints. */
export function resolveCreatedAt(fresh: boolean, now: number = Date.now()): number {
  if (typeof window === "undefined") return now;
  try {
    const stored = Number(window.sessionStorage.getItem(CREATED_AT_KEY));
    if (!fresh && Number.isSafeInteger(stored) && stored > 0) return stored;
    window.sessionStorage.setItem(CREATED_AT_KEY, String(now));
  } catch { /* storage unavailable: this mount's age */ }
  return now;
}

/** When this tab last wrote its registry entry (every heartbeat), or null. */
export function readLastBeat(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = Number(window.sessionStorage.getItem(LAST_BEAT_KEY));
    return Number.isSafeInteger(stored) && stored > 0 ? stored : null;
  } catch {
    return null;
  }
}

export function writeLastBeat(now: number): void {
  try {
    window.sessionStorage.setItem(LAST_BEAT_KEY, String(now));
  } catch { /* storage unavailable: a reload keeps its age */ }
}

/** Pure: a reload whose last beat is older than the registry TTL. Scanners
 *  saw the tab dead meanwhile and may have put its fans in another tab
 *  (acked ok), so it must come back young (`resolveCreatedAt(true)`) and give
 *  them up, as a live tab does on a stale tick. No beat recorded: not stale
 *  (every beat records one, so only a reload before the first beat, ms after
 *  mount, has none). */
export function isStaleReload(lastBeat: number | null, now: number): boolean {
  return lastBeat !== null && now - lastBeat > GROUP_HEARTBEAT_TTL_MS;
}

/** Pure: the live tabs older than `me` (earlier createdAt; on a tie, the
 *  smaller tab id, so a tie still has one winner). A fan two tabs hold stays
 *  with the oldest: each tab drops what an older one holds, at mount and on
 *  every heartbeat, so both sides of a duplicate agree who yields. */
export function olderTabs<T extends { tabId: string; createdAt: number }>(
  tabs: readonly T[], me: { tabId: string; createdAt: number },
): T[] {
  return tabs.filter((t) => t.tabId !== me.tabId
    && (t.createdAt < me.createdAt || (t.createdAt === me.createdAt && t.tabId < me.tabId)));
}

/** How many of `slots` have a cached chats row whose last message is the
 *  Fan's (the first cached copy of the row counts, as before). */
export function countUnresponded(qc: QueryClient, slots: readonly GroupSlot[]): number {
  const want = new Map(slots.map((s) => [`${s.accountId}:${s.fanId}`, s]));
  const found = new Map<string, OFChatItem>();
  const entries = qc.getQueriesData<{ pages: { rows: OFChatItem[] }[] }>({ queryKey: ["chats"] });
  for (const [, data] of entries) {
    if (!data?.pages) continue;
    for (const p of data.pages) for (const c of p.rows) {
      const k = `${c.__accountId ?? ""}:${c.withUser.id}`;
      if (want.has(k) && !found.has(k)) found.set(k, c);
    }
  }
  let n = 0;
  for (const [k, s] of want) {
    const lm = found.get(k)?.lastMessage;
    if (!lm) continue;
    if (lm.fromUser?.id != null && !sameUserId(lm.fromUser.id, s.accountId)) n++;
  }
  return n;
}
