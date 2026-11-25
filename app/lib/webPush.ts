"use client";


import { useSyncExternalStore } from "react";

import { relay, RelayError } from "@/lib/relay";
import { openNotification } from "@/lib/notificationLink";
import { hasShellNotify } from "@/lib/osNotify";
import { swEnabled } from "@/lib/registerImageSW";
import { pushBody, pushWanted } from "@/lib/pushPrefs";
import type { NotifSettings } from "@/lib/notifSettings";

export interface PushPayload {
  v?: number;
  tag?: string;
  title?: string;
  body?: string;
  href?: string;
  type?: string;
  account_id?: string;
  icon?: string;
}

export interface PushState {
  id: string | null;
  failed: string | null;
}

export const SYNC_DEBOUNCE_MS = 1_000;
const READY_MS = 5_000;

let state: PushState = { id: null, failed: null };
// Bumped by logout: an in-flight PUT/DELETE must not revive the id.
let generation = 0;
let synced: string | null = null;
const OFF = "off";
const listeners = new Set<() => void>();

function set(next: Partial<PushState>): void {
  state = { ...state, ...next };
  for (const fn of listeners) fn();
}

export function pushSupported(): boolean {
  return typeof window !== "undefined" && swEnabled() && "serviceWorker" in navigator &&
    "PushManager" in window && typeof Notification !== "undefined" && !hasShellNotify();
}

export function isPushLive(): boolean {
  return state.id !== null;
}

export function pushId(): string | null {
  return state.id;
}

export function usePushState(): PushState {
  return useSyncExternalStore(
    (fn) => { listeners.add(fn); return () => { listeners.delete(fn); }; },
    () => state,
    () => state,
  );
}

function relayReason(e: unknown): string | null {
  const body = e instanceof RelayError ? (e.body as { reason?: unknown; detail?: { reason?: unknown } } | null) : null;
  const r = body && typeof body === "object" ? body.reason ?? body.detail?.reason : undefined;
  return typeof r === "string" && r ? r : null;
}

export function why(e: unknown): string {
  return relayReason(e) ?? (e instanceof Error ? e.message : String(e));
}

async function registration(): Promise<ServiceWorkerRegistration> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("no service worker")), READY_MS);
  });
  try {
    return await Promise.race([navigator.serviceWorker.ready, late]);
  } finally {
    clearTimeout(timer);
  }
}

function fromB64url(s: string): Uint8Array<ArrayBuffer> {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i);
  return out;
}

function sameKey(have: ArrayBuffer | null | undefined, want: Uint8Array): boolean {
  if (!have) return false;
  const a = new Uint8Array(have);
  return a.length === want.length && a.every((x, i) => x === want[i]);
}

export const NOT_READY = "push is still starting, try again";
export const KEY_CHANGED = "the relay's push key changed, tap again";
const LOGGED_OUT = "signed out meanwhile";
const dropped = (e: unknown) => e instanceof Error && e.message === LOGGED_OUT;

let key: Uint8Array<ArrayBuffer> | null = null;
let reg: ServiceWorkerRegistration | null = null;
let stale: PushSubscription | null = null;

function staleOf(sub: PushSubscription | null, k: Uint8Array): PushSubscription | null {
  return sub && !sameKey(sub.options.applicationServerKey, k) ? sub : null;
}

let priming: Promise<void> | null = null;
let primeFailure: unknown = null;

async function ready(): Promise<{ key: Uint8Array<ArrayBuffer>; reg: ServiceWorkerRegistration }> {
  if (!key || !reg) {
    priming ??= (async () => {
      const r = reg ?? await registration();
      const k = key ?? fromB64url((await relay.get<{ key: string }>("/push/key")).key);
      stale = staleOf(await r.pushManager.getSubscription(), k);
      reg = r;
      key = k;
    })().finally(() => { priming = null; });
    await priming;
  }
  if (!key || !reg) throw new Error(NOT_READY);
  return { key, reg };
}

export function primePush(): Promise<void> {
  if (!pushSupported()) return Promise.resolve();
  return ready().then(() => { primeFailure = null; }, (e) => { primeFailure = e; set({ failed: why(e) }); });
}

async function put(sub: PushSubscription, settings: NotifSettings, gen: number): Promise<string> {
  const keys = sub.toJSON().keys ?? {};
  const prefs = pushBody(settings);
  try {
    const { id } = await relay.put<{ id: string }>("/push/subscription", {
      endpoint: sub.endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth }, ...prefs,
    });
    if (gen !== generation) return id;
    synced = JSON.stringify(prefs);
    set({ id, failed: null });
    return id;
  } catch (e) {
    if (gen !== generation) throw e;
    const gone = e instanceof RelayError && [401, 403, 404].includes(e.status);
    if (gone || !state.id) synced = null;
    set({ id: gone ? null : state.id, failed: why(e) });
    throw e;
  }
}

const applicationServerKey = (k: Uint8Array<ArrayBuffer>) => ({ userVisibleOnly: true, applicationServerKey: k });

export async function subscribePush(settings: NotifSettings): Promise<string> {
  try {
    if (!pushSupported()) throw new Error("not supported here");
    if (!key || !reg) {
      const failure = relayReason(primeFailure) ? primeFailure : new Error(NOT_READY);
      void primePush();
      throw failure;
    }
    const dropping = stale?.unsubscribe().catch(() => false);
    let sub: PushSubscription;
    try {
      sub = await reg.pushManager.subscribe(applicationServerKey(key));
    } catch (e) {
      if (!dropping || !(await dropping)) throw e;
      stale = null;
      throw new Error(KEY_CHANGED);
    }
    stale = null;
    return await queued((gen) => put(sub, settings, gen));
  } catch (e) {
    failed(e);
    throw e;
  }
}

async function syncNow(settings: NotifSettings, gen: number): Promise<void> {
  const k = await ready();
  let sub = await k.reg.pushManager.getSubscription();
  stale = staleOf(sub, k.key);
  if (stale) {
    synced = null;
    set({ id: null, failed: "the relay's push key changed" });
    return;
  }
  sub ??= await k.reg.pushManager.subscribe(applicationServerKey(k.key));
  await put(sub, settings, gen);
}

async function unsubscribeNow(gen: number): Promise<void> {
  synced = null;
  set({ id: null });
  const sub = await (reg ?? await registration().catch(() => null))?.pushManager.getSubscription();
  if (sub) await relay.delete("/push/subscription", undefined, { endpoint: sub.endpoint });
  if (gen === generation) synced = OFF;
}

let chain: Promise<unknown> = Promise.resolve();
function queued<T>(run: (gen: number) => Promise<T>): Promise<T> {
  const gen = generation;
  const next = chain.then(() => {
    if (gen !== generation) throw new Error(LOGGED_OUT);
    return run(gen);
  });
  chain = next.catch(() => undefined);
  return next;
}
const failed = (e: unknown) => { if (!dropped(e)) set({ failed: why(e) }); };

export function unsubscribePush(): Promise<void> {
  return pushSupported() ? queued(unsubscribeNow).catch(failed) : Promise.resolve();
}

let syncTimer: ReturnType<typeof setTimeout> | null = null;
let syncForce = false;

export function syncPush(settings: NotifSettings, { force = false }: { force?: boolean } = {}): void {
  if (!pushSupported()) return;
  if (syncTimer) clearTimeout(syncTimer);
  syncForce ||= force;
  syncTimer = setTimeout(() => {
    const forced = syncForce;
    syncTimer = null;
    syncForce = false;
    void queued(async (gen) => {
      if (!pushWanted(settings)) return synced === OFF && !forced ? undefined : unsubscribeNow(gen);
      if (Notification.permission !== "granted") return;
      if (!forced && state.id && synced === JSON.stringify(pushBody(settings))) return;
      await syncNow(settings, gen);
    }).catch(failed);
  }, SYNC_DEBOUNCE_MS);
}

export function forgetPush(): void {
  generation++;
  if (syncTimer) clearTimeout(syncTimer);
  syncTimer = null;
  syncForce = false;
  synced = null;
  set({ id: null });
}

export async function showViaWorker(title: string, options: NotificationOptions): Promise<void> {
  await (await registration()).showNotification(title, options);
}

export interface TestPushResult {
  status?: number;
  reason?: string;
}

export function testPush(delayS: number): Promise<TestPushResult | null> {
  if (!state.id) return Promise.reject(new Error("push is off"));
  return relay.post<TestPushResult | null>("/push/test", { id: state.id, delay_s: delayS });
}

export function iosTab(): boolean {
  if (typeof navigator === "undefined") return false;
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
  const installed = (navigator as { standalone?: boolean }).standalone === true ||
    (typeof matchMedia === "function" && matchMedia("(display-mode: standalone)").matches);
  return ios && !installed;
}

function onWorkerMessage(handle: (d: { type?: unknown; href?: unknown; payload?: unknown }, e: MessageEvent) => void): () => void {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return () => {};
  const sw = navigator.serviceWorker;
  const onMessage = (e: MessageEvent) => {
    const d = e.data as { type?: unknown } | null;
    if (d && typeof d === "object") handle(d, e);
  };
  sw.addEventListener("message", onMessage);
  sw.startMessages?.();
  return () => sw.removeEventListener("message", onMessage);
}

export function listenNotificationClicks(): () => void {
  return onWorkerMessage((d) => {
    if (d.type === "open-notification" && typeof d.href === "string" && d.href.startsWith("/") && !d.href.startsWith("//")) {
      openNotification(d.href);
    }
  });
}

export function listenPushNotices(onNotice: (payload: unknown) => boolean): () => void {
  return onWorkerMessage((d, e) => {
    if (d.type !== "push-notice") return;
    let took = false;
    try {
      took = onNotice(d.payload) === true;
    } finally {
      e.ports?.[0]?.postMessage(took);
    }
  });
}

export function resetPushForTests(): void {
  if (syncTimer) clearTimeout(syncTimer);
  syncTimer = null;
  chain = Promise.resolve();
  syncForce = false;
  synced = null;
  key = null;
  reg = null;
  stale = null;
  priming = null;
  primeFailure = null;
  state = { id: null, failed: null };
}
