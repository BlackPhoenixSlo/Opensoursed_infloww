import type { QueryClient } from "@tanstack/react-query";

import { GROUP_HEARTBEAT_TTL_MS, cleanSlots, parseSlotsParam, type GroupSlot } from "@/lib/groupChannel";
import { fanIdFromParam, sameUserId } from "@/lib/fanId";
import type { OFChatItem } from "@/lib/relay";

export const SLOTS_KEY = "chatterly:group-slots";
export const TAB_ID_KEY = "chatterly:group-tab-id";
export const CREATED_AT_KEY = "chatterly:group-tab-created-at";
export const LAST_BEAT_KEY = "chatterly:group-tab-last-beat";

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
  }
}

export interface SeedParams {
  seeds: GroupSlot[];
  spawnToken: string | null;
  rest: string | null;
}

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
  // Not Number(): a Fansly snowflake does not survive float64.
  const fan = fanIdFromParam(rawAdd.slice(idx + 1));
  if (!accountId || fan == null) return { seeds: [], spawnToken, rest };
  return { seeds: [{ accountId, fanId: fan }], spawnToken, rest };
}

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

export function resolveTabId(fresh: boolean): string {
  if (typeof window === "undefined") return "";
  try {
    const existing = window.sessionStorage.getItem(TAB_ID_KEY);
    // fresh mints a new id: some browsers copy sessionStorage into a window.open'd child, which would share its opener's id.
    if (existing && !fresh) return existing;
    const id = genId();
    window.sessionStorage.setItem(TAB_ID_KEY, id);
    return id;
  } catch {
    return genId();
  }
}

export function resolveCreatedAt(fresh: boolean, now: number = Date.now()): number {
  if (typeof window === "undefined") return now;
  try {
    const stored = Number(window.sessionStorage.getItem(CREATED_AT_KEY));
    if (!fresh && Number.isSafeInteger(stored) && stored > 0) return stored;
    window.sessionStorage.setItem(CREATED_AT_KEY, String(now));
  } catch { }
  return now;
}

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
  } catch { }
}

export function isStaleReload(lastBeat: number | null, now: number): boolean {
  // A reload after the TTL was seen dead by scanners, who may have moved its fans: it must come back young and yield them.
  return lastBeat !== null && now - lastBeat > GROUP_HEARTBEAT_TTL_MS;
}

export function olderTabs<T extends { tabId: string; createdAt: number }>(
  tabs: readonly T[], me: { tabId: string; createdAt: number },
): T[] {
  return tabs.filter((t) => t.tabId !== me.tabId
    && (t.createdAt < me.createdAt || (t.createdAt === me.createdAt && t.tabId < me.tabId)));
}

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
