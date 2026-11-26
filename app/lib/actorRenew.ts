export const ACTOR_RENEW_MS = 5 * 60 * 1000;

let inflight: Promise<boolean> | null = null;
let timer: ReturnType<typeof setInterval> | null = null;
let first: Promise<boolean> | null = null;

export function renewActor(): Promise<boolean> {
  inflight ??= fetch("/auth/actor", {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(10_000),
  })
    .then((r) => r.ok, () => false)
    .finally(() => { inflight = null; });
  return inflight;
}

// Sign-in clears oi_actor, so the first cell-mode call of a page load mints one before any data Cell is asked.
function keepFresh(): Promise<boolean> | null {
  if (typeof window === "undefined") return null;
  if (timer == null) {
    timer = setInterval(() => { void renewActor(); }, ACTOR_RENEW_MS);
    first = renewActor();
  }
  return first;
}

export function resetActorRenewal(): void {
  if (timer != null) clearInterval(timer);
  timer = null;
  inflight = null;
}

export async function fetchRenewing(url: string, init: RequestInit): Promise<Response> {
  await keepFresh();
  const r = await fetch(url, init);
  if (r.status !== 401 || url.startsWith("/auth/")) return r;
  const body = await r.clone().json().catch(() => null);
  const error = body?.detail?.error;
  if (typeof error !== "string" || !error.startsWith("actor_") || !(await renewActor())) return r;
  return fetch(url, init);
}
