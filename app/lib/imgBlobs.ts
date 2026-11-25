const MAX = 300;
const blobs = new Map<string, Promise<string | null>>();

export function imgIdentity(proxied: string): string | null {
  const q = proxied.indexOf("?");
  if (q < 0 || proxied.slice(0, q) !== "/img") return null;
  const params = new URLSearchParams(proxied.slice(q + 1));
  const u = params.get("u");
  if (!u) return null;
  try {
    const url = new URL(u);
    return `${params.get("account_id") ?? ""}|${url.host}${url.pathname}`;
  } catch {
    return null;
  }
}

export function cachedImg(key: string): Promise<string | null> | undefined {
  const p = blobs.get(key);
  if (p) { blobs.delete(key); blobs.set(key, p); }
  return p;
}

export function rememberImg(key: string, load: Promise<string | null>): Promise<string | null> {
  const p = load.catch(() => null);
  blobs.delete(key);
  blobs.set(key, p);
  void p.then((u) => { if (!u && blobs.get(key) === p) blobs.delete(key); });
  while (blobs.size > MAX) {
    const [old, op] = blobs.entries().next().value as [string, Promise<string | null>];
    blobs.delete(old);
    // Revoked only on eviction; an <img> that already decoded it keeps painting.
    void op.then((u) => { if (u) URL.revokeObjectURL(u); });
  }
  return p;
}

export function preloadImg(proxied: string): void {
  const key = imgIdentity(proxied);
  if (!key || blobs.has(key) || typeof fetch === "undefined") return;
  rememberImg(key, fetch(proxied, { priority: "low" } as RequestInit)
    .then((r) => (r.ok ? r.blob() : null))
    .then((b) => (b ? URL.createObjectURL(b) : null)));
}

export function resetImgBlobs(): void {
  blobs.clear();
}
