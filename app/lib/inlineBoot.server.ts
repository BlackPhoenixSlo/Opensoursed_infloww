/**
 * The server half of the HTML's inline boot (lib/inlineBoot.ts): which relay GETs a document load starts, and
 * starting them. Called by the root layout per request: the promises are this request's, never cached or shared, so
 * one browser's answers never land in another's HTML.
 *
 * Which: the document's route (app/proxy.ts tags a document GET of `/` or `/messages-pro` with its path and query)
 * and what AuthGate starts there: /auth/me and /chatter/me (the gate waits for both), the Dashboard's Applied
 * settings, and the screen's bundle at the key the browser guesses too (lib/screenEntry.ts `bootScreen`, from the
 * cookies that mirror its inputs; none: the browser starts it, as before).
 *
 * Starting them: each against RELAY_URL (the relay the rewrites front, on loopback or the compose network; never a
 * host the request names) with the request's Cookie header, which is what the browser would have sent there itself.
 * `INLINE_TIMEOUT_MS` past the bundle's own 2 s deadline (service/screens_api.py DEADLINE_MS), an answer is dropped
 * (null): the response then ends and the browser fetches it itself. Never rejects.
 */
import type { InlineAnswer, InlineData } from "@/lib/inlineBoot";
import { BOOTED, inlineKey } from "@/lib/inlineBoot";
import { bundlePath } from "@/lib/screenKey";
import { bootScreen, type CookieRead } from "@/lib/screenEntry";

export const INLINE_TIMEOUT_MS = 2_500;

/** The GETs a document load of `pathAndSearch` starts (inline keys), given its cookies (`cookie`). */
export function inlinePaths(pathAndSearch: string | null, cookie: CookieRead): string[] {
  if (!pathAndSearch) return [];
  const { pathname } = new URL(pathAndSearch, "http://x");
  if (!BOOTED.has(pathname)) return [];
  const s = bootScreen(pathAndSearch, cookie);
  return ["/auth/me", "/chatter/me", ...(pathname === "/" ? ["/admin/settings/applied"] : []), ...(s ? [bundlePath(s)] : [])]
    .map(inlineKey);
}

/** Start `paths` on `relayUrl` with `cookie`; null when there is nothing to start. */
export function startInline(paths: string[], cookie: string | null, relayUrl: string): InlineData | null {
  if (!cookie || !paths.length) return null;
  const base = relayUrl.replace(/\/+$/, "");
  const get = async (p: string): Promise<InlineAnswer> => {
    try {
      const r = await fetch(base + p, {
        headers: { cookie, accept: "application/json" },
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(INLINE_TIMEOUT_MS),
      });
      if (r.status < 200 || r.status >= 500 || (r.status >= 300 && r.status < 400)) return null;
      return { status: r.status, body: await r.text() };
    } catch {
      return null;
    }
  };
  return Object.fromEntries(paths.map((p) => [p, get(p)]));
}
