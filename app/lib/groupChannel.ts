"use client";

import { fanIdFromParam, isValidFanId, sameUserId, type FanId } from "@/lib/fanId";


export const GROUP_CHANNEL_NAME = "chatterly-group";
export const GROUP_WINDOW_NAME = "chatterly-group-tab";
export const GROUP_HEARTBEAT_MS = 2000;
export const GROUP_HEARTBEAT_TTL_MS = 6000;
export const GROUP_TAB_KEY_PREFIX = "chatterly:group-tab:";
export const GROUP_SLOT_CAP = 8;
// Absorbs a near-simultaneous cold-start spawn from another source tab.
const SPAWN_DEFER_MS = 60;
const ADD_ACK_TIMEOUT_MS = 400;

export interface GroupSlot { accountId: string; fanId: FanId }

export function sameSlot(a: GroupSlot, b: GroupSlot): boolean {
  return a.accountId === b.accountId && sameUserId(a.fanId, b.fanId);
}

export function isGroupSlot(x: unknown): x is GroupSlot {
  if (!x || typeof x !== "object") return false;
  const { accountId, fanId } = x as { accountId?: unknown; fanId?: unknown };
  return typeof accountId === "string" && accountId !== "" && isValidFanId(fanId);
}

export const listOf = (x: unknown): readonly unknown[] => (Array.isArray(x) ? x : []);

export function cleanSlots(x: unknown): GroupSlot[] {
  return listOf(x).filter(isGroupSlot).map((s) => ({ accountId: s.accountId, fanId: s.fanId }));
}

export interface GroupTabRegistry {
  tabId: string;
  createdAt: number;
  heartbeat: number;
  slots: GroupSlot[];
}

export type GroupChannelMessage =
  | { type: "add"; tabId: string; reqId: string; accountId: string; fanId: FanId }
  | { type: "add-ack"; tabId: string; reqId: string; ok: boolean }
  | { type: "replace"; tabId: string; reqId: string; slots: GroupSlot[] }
  | { type: "focus"; tabId: string }
  | { type: "claim"; tabId: string; spawnToken: string };

export type ReceivedGroupMessage =
  | Exclude<GroupChannelMessage, { type: "add" } | { type: "replace" }>
  | { type: "add"; tabId: string; reqId: string; accountId: unknown; fanId: unknown }
  | { type: "replace"; tabId: string; reqId: string; slots: readonly unknown[] };

const str = (v: unknown): v is string => typeof v === "string";

export function cleanGroupMessage(x: unknown): ReceivedGroupMessage | null {
  if (!x || typeof x !== "object") return null;
  const m = x as Record<string, unknown>;
  if (!str(m.tabId)) return null;
  const tabId = m.tabId;
  switch (m.type) {
    case "add":
      return str(m.reqId) ? { type: "add", tabId, reqId: m.reqId, accountId: m.accountId, fanId: m.fanId } : null;
    case "replace":
      return str(m.reqId) ? { type: "replace", tabId, reqId: m.reqId, slots: listOf(m.slots) } : null;
    case "add-ack":
      return str(m.reqId) ? { type: "add-ack", tabId, reqId: m.reqId, ok: m.ok === true } : null;
    case "focus":
      return { type: "focus", tabId };
    case "claim":
      return str(m.spawnToken) ? { type: "claim", tabId, spawnToken: m.spawnToken } : null;
    default:
      return null;
  }
}

export function cleanGroupTab(x: unknown, now: number): GroupTabRegistry | null {
  if (!x || typeof x !== "object") return null;
  const r = x as Record<string, unknown>;
  const { tabId, heartbeat, createdAt } = r;
  if (!str(tabId) || typeof heartbeat !== "number" || !Array.isArray(r.slots)) return null;
  if (now - heartbeat > GROUP_HEARTBEAT_TTL_MS) return null;
  return {
    tabId, heartbeat, slots: cleanSlots(r.slots),
    createdAt: typeof createdAt === "number" && createdAt > 0 ? createdAt : heartbeat,
  };
}

export const GROUP_REPLACE_EVENT = "chatterly:group-replace";

export function readAllLiveGroupTabs(): GroupTabRegistry[] {
  if (typeof window === "undefined") return [];
  const out: GroupTabRegistry[] = [];
  try {
    const now = Date.now();
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (!key || !key.startsWith(GROUP_TAB_KEY_PREFIX)) continue;
      const raw = window.localStorage.getItem(key);
      if (!raw) continue;
      try {
        const tab = cleanGroupTab(JSON.parse(raw) as unknown, now);
        if (tab) out.push(tab);
      } catch { }
    }
  } catch { }
  return out;
}

export function writeGroupTabRegistry(tabId: string, createdAt: number, slots: GroupSlot[]): void {
  if (typeof window === "undefined") return;
  try {
    const r: GroupTabRegistry = { tabId, createdAt, heartbeat: Date.now(), slots };
    window.localStorage.setItem(GROUP_TAB_KEY_PREFIX + tabId, JSON.stringify(r));
  } catch { }
}

export function removeGroupTabRegistry(tabId: string): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(GROUP_TAB_KEY_PREFIX + tabId); } catch {}
}

let groupRef: { tabId: string | null; spawnToken: string | null; win: Window } | null = null;

let sourceChannel: BroadcastChannel | null = null;
const pendingAcks = new Map<string, (ok: boolean) => void>();

function ensureSourceChannel(): BroadcastChannel | null {
  if (typeof window === "undefined") return null;
  if (sourceChannel) return sourceChannel;
  try {
    sourceChannel = new BroadcastChannel(GROUP_CHANNEL_NAME);
    sourceChannel.onmessage = (e: MessageEvent<unknown>) => {
      const msg = cleanGroupMessage(e.data);
      if (!msg) return;
      if (msg.type === "add-ack") {
        const resolver = pendingAcks.get(msg.reqId);
        if (resolver) {
          pendingAcks.delete(msg.reqId);
          resolver(msg.ok);
        }
        return;
      }
      if (msg.type === "claim") {
        if (groupRef && groupRef.spawnToken && groupRef.spawnToken === msg.spawnToken) {
          groupRef.tabId = msg.tabId;
        }
        return;
      }
    };
  } catch {
    sourceChannel = null;
  }
  return sourceChannel;
}

function broadcast(msg: GroupChannelMessage): void {
  const ch = ensureSourceChannel();
  if (!ch) return;
  try { ch.postMessage(msg); } catch { }
}

export type OpenGroupResult =
  | { kind: "broadcast" }
  | { kind: "focused" }
  | { kind: "opened" }
  | { kind: "self" };

function tryFocusGroupTab(tabId: string): void {
  // Held window ref is only safe when known to belong to the target tab; else broadcast focus.
  if (groupRef && !groupRef.win.closed && groupRef.tabId === tabId) {
    try { groupRef.win.focus(); } catch { }
  }
  broadcast({ type: "focus", tabId });
}

function waitForAddAck(reqId: string): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    pendingAcks.set(reqId, resolve);
    window.setTimeout(() => {
      if (pendingAcks.delete(reqId)) resolve(false);
    }, ADD_ACK_TIMEOUT_MS);
  });
}

function genReqId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function spawnGroupTab(accountId: string, fanId: FanId, overflow: boolean): void {
  const spawnToken = genReqId();
  const url = `/group?add=${encodeURIComponent(accountId)}:${fanId}&spawn=${encodeURIComponent(spawnToken)}`;
  // Listen before spawning: the new tab's `claim` may arrive before any later broadcast opens the channel.
  ensureSourceChannel();
  if (overflow) {
    const win = window.open(url, "_blank");
    if (win) groupRef = { tabId: null, spawnToken, win };
  } else {
    const win = window.open(url, GROUP_WINDOW_NAME);
    if (win) groupRef = { tabId: null, spawnToken, win };
  }
}

function encodeSlots(slots: GroupSlot[]): string {
  return slots.map((s) => `${encodeURIComponent(s.accountId)}:${s.fanId}`).join(",");
}

// Parse ids as text: Number() truncates Fansly snowflakes to a ghost id.
export function parseSlotsParam(raw: string): GroupSlot[] {
  const out: GroupSlot[] = [];
  for (const part of raw.split(",")) {
    const idx = part.lastIndexOf(":");
    if (idx <= 0) continue;
    const accountId = decodeURIComponent(part.slice(0, idx));
    const fanId = fanIdFromParam(part.slice(idx + 1));
    if (!accountId || fanId == null) continue;
    const slot = { accountId, fanId };
    if (out.some((s) => sameSlot(s, slot))) continue;
    out.push(slot);
  }
  return out.slice(0, GROUP_SLOT_CAP);
}

export async function openGroupTabWithSlots(slots: GroupSlot[]): Promise<OpenGroupResult> {
  if (typeof window === "undefined") return { kind: "opened" };
  const wanted = slots.slice(0, GROUP_SLOT_CAP);
  if (wanted.length === 0) return { kind: "self" };

  if (window.location?.pathname === "/group") {
    window.dispatchEvent(new CustomEvent(GROUP_REPLACE_EVENT, { detail: { slots: wanted } }));
    return { kind: "self" };
  }

  const live = readAllLiveGroupTabs().sort((a, b) => b.heartbeat - a.heartbeat);
  const target = live[0];
  if (target) {
    const reqId = genReqId();
    const ackPromise = waitForAddAck(reqId);
    broadcast({ type: "replace", tabId: target.tabId, reqId, slots: wanted });
    tryFocusGroupTab(target.tabId);
    if (await ackPromise) return { kind: "broadcast" };
  }

  const spawnToken = genReqId();
  ensureSourceChannel();
  const url = `/group?slots=${encodeSlots(wanted)}&spawn=${encodeURIComponent(spawnToken)}`;
  const win = window.open(url, GROUP_WINDOW_NAME);
  if (win) groupRef = { tabId: null, spawnToken, win };
  return { kind: "opened" };
}

export async function openGroupTab(accountId: string, fanId: FanId): Promise<OpenGroupResult> {
  if (typeof window === "undefined") return { kind: "opened" };

  if (typeof window.location !== "undefined" &&
      window.location.pathname === "/group") {
    return { kind: "self" };
  }

  const live = readAllLiveGroupTabs();

  const owner = live.find((t) => t.slots.some((s) => sameSlot(s, { accountId, fanId })));
  if (owner) {
    tryFocusGroupTab(owner.tabId);
    return { kind: "focused" };
  }

  const withRoom = live
    .filter((t) => t.slots.length < GROUP_SLOT_CAP)
    .sort((a, b) => b.heartbeat - a.heartbeat);
  const target = withRoom[0];
  if (target) {
    const reqId = genReqId();
    const ackPromise = waitForAddAck(reqId);
    broadcast({ type: "add", tabId: target.tabId, reqId, accountId, fanId });
    tryFocusGroupTab(target.tabId);
    const accepted = await ackPromise;
    if (accepted) return { kind: "broadcast" };
    spawnGroupTab(accountId, fanId, true);
    return { kind: "opened" };
  }

  if (live.length === 0) {
    await new Promise<void>((r) => window.setTimeout(r, SPAWN_DEFER_MS));
    const recheck = readAllLiveGroupTabs();
    if (recheck.length > 0) {
      return openGroupTab(accountId, fanId);
    }
  }

  spawnGroupTab(accountId, fanId, live.length > 0);
  return { kind: "opened" };
}
