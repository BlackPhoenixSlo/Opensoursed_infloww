/**
 * The tab's one shared clock for data ages and the No-live-connection mark
 * (docs/spec/watched-creator-refresher/phase-03-data-age-live-connection-mark.md, Ticking): one `setInterval` of
 * TICK_MS for the whole tab, running only while something subscribes and the document is visible, never one timer
 * per badge or tab; a hidden tab has none, and turning visible ticks at once (a throttled background timer never
 * shows a wrong age). `now()` is the tab's time floored to TICK_MS, so a `useSyncExternalStore` snapshot built on it
 * is stable between ticks.
 *
 * Beside it, the Relay-clock offset (tab clock minus Relay clock, `serverOffset`): set from
 * each network accounts answer's `now` (useAccounts' seed) and each stream ping's `ts` (lib/events), the latest call
 * winning; 0 until one lands. An Event stream envelope's `now` never sets it (a replayed event's `now` is as old as its
 * send). A module singleton, as `eventBus`.
 */

export const TICK_MS = 15_000;

const subscribers = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;
let offsetMs = 0;
let offsetKnown = false;

const notify = () => { for (const fn of [...subscribers]) fn(); };

const visible = () => typeof document === "undefined" || document.visibilityState !== "hidden";
const start = () => { timer ??= setInterval(notify, TICK_MS); };
const stop = () => {
  if (timer === null) return;
  clearInterval(timer);
  timer = null;
};
const onVisibility = () => {
  if (!visible()) return stop();
  notify();
  start();
};

/** The tab's time at the current tick (epoch ms, floored to TICK_MS). */
export function now(): number {
  return Math.floor(Date.now() / TICK_MS) * TICK_MS;
}

/** Call `fn` on every tick (and when the offset moves, or the tab turns visible); returns the unsubscribe. The
 *  interval starts with the first subscriber (while visible) and stops with the last. */
export function subscribe(fn: () => void): () => void {
  subscribers.add(fn);
  if (subscribers.size === 1 && typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibility);
  }
  if (visible()) start();
  return () => {
    if (!subscribers.delete(fn) || subscribers.size > 0) return;
    stop();
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
  };
}

/** The tab's clock minus the Relay's (ms); 0 before any accounts answer. */
export function relayOffset(): number {
  return offsetMs;
}

/** Whether a Relay time has set the offset yet (before: `relayOffset()` is a 0 guess). */
export function relayOffsetKnown(): boolean {
  return offsetKnown;
}

/** The Relay's clock now, as the tab estimates it (epoch ms): the time to stamp anything compared with a Relay time
 *  (an event's `at`, OF's `createdAt`). */
export function relayNow(): number {
  return Date.now() - offsetMs;
}

/** The tab's clock minus the Relay's, from a Relay time (`now`, epoch ms) and the tab time it arrived at. */
export const serverOffset = (serverMs: number, receivedAt: number): number => receivedAt - serverMs;

/** Take a new offset (`serverOffset(relayNow, receivedAt)`); subscribers re-read when it moved. */
export function setRelayOffset(ms: number): void {
  if (!Number.isFinite(ms)) return;
  offsetKnown = true;
  if (ms === offsetMs) return;
  offsetMs = ms;
  notify();
}
