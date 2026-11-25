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

export function now(): number {
  return Math.floor(Date.now() / TICK_MS) * TICK_MS;
}

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

export function relayOffset(): number {
  return offsetMs;
}

export function relayOffsetKnown(): boolean {
  return offsetKnown;
}

export function relayNow(): number {
  return Date.now() - offsetMs;
}

export const serverOffset = (serverMs: number, receivedAt: number): number => receivedAt - serverMs;

// An event envelope's `now` never sets this: a replayed event's `now` is as old as its send.
export function setRelayOffset(ms: number): void {
  if (!Number.isFinite(ms)) return;
  offsetKnown = true;
  if (ms === offsetMs) return;
  offsetMs = ms;
  notify();
}
