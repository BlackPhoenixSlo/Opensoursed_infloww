import type { NotificationItem } from "@/lib/moneyRailStorage";
import { MONEY_TYPES, NOTIF_PAGE_SIZE, notifPath, parseList, type MoneyTypeKey } from "@/lib/notifText";
import { relay, RelayError } from "@/lib/relay";

export function moneyPath(types: readonly MoneyTypeKey[]): string {
  const asked = MONEY_TYPES.filter((t) => types.includes(t));
  const q = new URLSearchParams({ types: asked.join(","), limit: String(NOTIF_PAGE_SIZE), offset: "0" });
  return `/api/of/v2/users/notifications/money?${q.toString()}`;
}

export function splitMoneyBody(
  raw: unknown, types: readonly MoneyTypeKey[],
): Record<MoneyTypeKey, NotificationItem[] | RelayError> {
  const body = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
  const errors = body.errors && typeof body.errors === "object" ? body.errors as Record<string, unknown> : {};
  const out = {} as Record<MoneyTypeKey, NotificationItem[] | RelayError>;
  for (const t of types) {
    const err = errors[t] as { status?: unknown; detail?: unknown } | undefined;
    out[t] = err
      ? new RelayError(typeof err.status === "number" ? err.status : 502, { detail: err.detail })
      : parseList(body[t]);
  }
  return out;
}

export function isNoRoute(e: unknown): boolean {
  return e instanceof RelayError && e.status === 404
      // FastAPI's own 404; an unknown Creator's 404 says otherwise
    && (e.body as { detail?: unknown } | null)?.detail === "Not Found";
}

interface Waiter {
  type: MoneyTypeKey;
  signal?: AbortSignal;
  resolve: (rows: NotificationItem[]) => void;
  reject: (e: unknown) => void;
}

const pending = new Map<string, Waiter[]>();
let noRoute = false;

function perType(aid: string, type: MoneyTypeKey, signal?: AbortSignal): Promise<NotificationItem[]> {
  return relay.get(notifPath(type), { accountId: aid, priority: "background" }, signal).then(parseList);
}

export function readMoneyList(aid: string, type: MoneyTypeKey, signal?: AbortSignal): Promise<NotificationItem[]> {
  if (noRoute) return perType(aid, type, signal);
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted();
    let waiters = pending.get(aid);
    if (!waiters) {
      waiters = [];
      pending.set(aid, waiters);
      setTimeout(() => void flush(aid), 0);
    }
    waiters.push({ type, signal, resolve, reject });
  });
}

async function flush(aid: string): Promise<void> {
  const all = pending.get(aid) ?? [];
  pending.delete(aid);
  const live = all.filter((w) => !w.signal?.aborted);
  for (const w of all) if (w.signal?.aborted) w.reject(w.signal.reason);
  if (live.length === 0) return;
  const types = MONEY_TYPES.filter((t) => live.some((w) => w.type === t));
  const ctl = new AbortController();
  const offs = live.map((w) => {
    const onAbort = () => {
      w.reject(w.signal!.reason);
      if (live.every((x) => x.signal?.aborted)) ctl.abort(w.signal!.reason);
    };
    w.signal?.addEventListener("abort", onAbort, { once: true });
    return () => w.signal?.removeEventListener("abort", onAbort);
  });
  try {
    const split = splitMoneyBody(
      await relay.get(moneyPath(types), { accountId: aid, priority: "background" }, ctl.signal), types);
    for (const w of live) {
      const v = split[w.type];
      if (v instanceof RelayError) w.reject(v);
      else w.resolve(v);
    }
  } catch (e) {
    if (isNoRoute(e)) {
      noRoute = true;
      for (const w of live) perType(aid, w.type, w.signal).then(w.resolve, w.reject);
    } else {
      for (const w of live) w.reject(e);
    }
  } finally {
    for (const off of offs) off();
  }
}

export function resetMoneyLists(): void {
  pending.clear();
  noRoute = false;
}
