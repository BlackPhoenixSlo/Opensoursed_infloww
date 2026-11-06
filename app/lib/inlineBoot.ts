/**
 * The HTML's inline boot: a document load of the Dashboard or Messages Pro gets its first relay answers (/auth/me,
 * /chatter/me, the Dashboard's Applied settings, the screen's bundle) in the same response as its HTML, so a phone
 * 250 ms away pays no third round trip for them (slop slow-connections: the bundle started at 580 ms, after the HTML
 * and the JS, and was the Dashboard's last answer).
 *
 * The root layout (server) starts those GETs on the relay with the request's own cookies (lib/inlineBoot.server.ts)
 * and does not wait: the shell and the JS go out at once, each answer streams in when the relay gave it (a promise
 * prop of `InlineBoot`, components/InlineBoot.tsx). Here, the browser's side: the first GET of such a URL (`take`)
 * gets that answer as if it had fetched it, once, for KEEP_MS after the document's boot; no answer (relay down, past
 * its time, a 5xx) is a miss, and the caller fetches as before. A URL nobody asks (another key: the guess was wrong)
 * is never used. Everything after it (a bundle's follow-up, a later /auth/me) is the network's.
 */

/** A relay answer as the server got it; null: none (the caller fetches). */
export type InlineAnswer = { status: number; body: string } | null;
/** Per URL (`inlineKey`), its answer when it lands. */
export type InlineData = Record<string, Promise<InlineAnswer>>;

/** The request header app/proxy.ts sets on a document GET of a booted route: its path and query. */
export const BOOT_PATH_HEADER = "x-chatterly-boot-path";
/** How long after the boot an inline answer may stand in for its first fetch. */
export const KEEP_MS = 10_000;
/** Query params that never change an answer's body: the share token and the bundle's open Creator (its priority). */
const IGNORED = ["t", "focus"];

let seeded: number | null = null;
const answers = new Map<string, Promise<InlineAnswer>>();

/** `url` (path + query) as an inline answer's key: the same URL less the params in IGNORED. */
export function inlineKey(url: string): string {
  const u = new URL(url, "http://x");
  for (const k of IGNORED) u.searchParams.delete(k);
  return u.pathname + u.search;
}

/** The document's inline answers (InlineBoot's render); once per document, a later call is ignored. */
export function seedInline(data: InlineData): void {
  if (seeded != null) return;
  seeded = Date.now();
  for (const [k, p] of Object.entries(data)) answers.set(k, p);
}

/** `url`'s inline answer as a Response, once. null at once when there is none to take (so the caller's fetch goes out
 * in the same tick as before); a promise of null when its answer turned out a miss (fetch it). */
export function takeInline(url: string): Promise<Response | null> | null {
  if (seeded == null || answers.size === 0) return null;
  if (Date.now() - seeded > KEEP_MS) {
    answers.clear();
    return null;
  }
  const k = inlineKey(url);
  const p = answers.get(k);
  if (!p) return null;
  answers.delete(k);
  // `p` is React's: on the client a Flight chunk, a thenable whose `then` returns nothing (no `.catch` chain), so
  // wrapped in a real Promise first.
  return new Promise<InlineAnswer>((res) => {
    try {
      p.then(res, () => res(null));
    } catch {
      res(null);
    }
  }).then((a) => {
    if (!a || a.status < 200 || a.status >= 500) return null;
    const empty = a.status === 204 || a.status === 205;
    return new Response(empty ? null : a.body, { status: a.status, headers: { "content-type": "application/json" } });
  });
}

/** Drop what is left (an identity switch: never another principal's answer). */
export function clearInline(): void {
  answers.clear();
}

/** Tests only. */
export function resetInline(): void {
  answers.clear();
  seeded = null;
}
