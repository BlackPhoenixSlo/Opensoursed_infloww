/**
 * imgBlobs.ts — the image bytes this tab already loaded through `/img`, as object URLs, by a signature-blind
 * identity (the Creator + the CDN host and path; OnlyFans re-signs a URL's query on every page it serves).
 *
 * MediaTile reads it before it fetches, so a tile whose URL was re-signed (a poll, a tab return), or that remounts
 * (an `eager` flip, a chat switch and back), paints its bytes with no request; the chat open's bundle preloads the
 * thread's newest thumbnails into it (`preloadImg`) before OnlyFans' page lands. A load that fails or aborts is
 * forgotten (the next tile fetches again). Bounded: the oldest entries go (their object URL revoked; an <img> that
 * already decoded it keeps painting).
 */

const MAX = 300;
const blobs = new Map<string, Promise<string | null>>();

/** `proxied`'s identity: `account|host/path` of its `/img?u=` CDN URL; null for anything else (blob:, by-hash). */
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

/** The object URL loaded (or loading) for `key`, newest-used kept longest. */
export function cachedImg(key: string): Promise<string | null> | undefined {
  const p = blobs.get(key);
  if (p) { blobs.delete(key); blobs.set(key, p); }
  return p;
}

/** Hold `load` (an object URL, or null: failed) as `key`'s bytes; returns it. */
export function rememberImg(key: string, load: Promise<string | null>): Promise<string | null> {
  const p = load.catch(() => null);
  // No revoke on replace: the only replace is MediaTile's race after a shared load failed (null, nothing to free),
  // and a live entry's URL may be painting in another tile.
  blobs.delete(key);
  blobs.set(key, p);
  void p.then((u) => { if (!u && blobs.get(key) === p) blobs.delete(key); });
  while (blobs.size > MAX) {
    const [old, op] = blobs.entries().next().value as [string, Promise<string | null>];
    blobs.delete(old);
    void op.then((u) => { if (u) URL.revokeObjectURL(u); });
  }
  return p;
}

/** Load `proxied` into the cache at low priority unless it is there (a preload: no tile waits on it yet). */
export function preloadImg(proxied: string): void {
  const key = imgIdentity(proxied);
  if (!key || blobs.has(key) || typeof fetch === "undefined") return;
  rememberImg(key, fetch(proxied, { priority: "low" } as RequestInit)
    .then((r) => (r.ok ? r.blob() : null))
    .then((b) => (b ? URL.createObjectURL(b) : null)));
}

/** Tests only. */
export function resetImgBlobs(): void {
  blobs.clear();
}
