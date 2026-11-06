/**
 * The server half of the HTML's inline boot (lib/inlineBoot.ts): which relay GETs a document load starts, and
 * starting them. Called by the root layout per request: the promises are this request's, never cached or shared, so
 * one browser's answers never land in another's HTML.
 *
 * Which: the document's route (app/proxy.ts tags a document GET of `/` or `/messages-pro` with its path and query)
 * and what AuthGate starts there: /auth/me and /chatter/me (the gate waits for both), the Dashboard's Applied
 * settings, and the screen's bundle at the key the browser would guess (lib/screenEntry.ts `entryScreen`, from the
 * cookies that mirror its inputs). The Dashboard's days need a zone: the saved entry's, else the browser's
 * (`TZ_COOKIE`); with neither (the first document load on this browser), no bundle (the browser starts it, as before).
 *
 * Starting them: each against RELAY_URL (the relay the rewrites front, on loopback or the compose network; never a
 * host the request names) with the request's Cookie header, which is what the browser would have sent there itself.
 * `INLINE_TIMEOUT_MS` past the bundle's own 2 s deadline (service/screens_api.py DEADLINE_MS), an answer is dropped
 * (null): the response then ends and the browser fetches it itself. Never rejects.
 */
import type { InlineAnswer, InlineData } from "@/lib/inlineBoot";
import { inlineKey } from "@/lib/inlineBoot";
import { bundlePath, screenKey } from "@/lib/screenKey";
import { entryScreen, parseDashboardEntry } from "@/lib/screenEntry";

export const INLINE_TIMEOUT_MS = 2_500;

function decoded(v: string | undefined): string | null {
  if (v == null) return null;
  try {
    return decodeURIComponent(v);
  } catch {
    return v;
  }
}

/** The GETs a document load of `pathAndSearch` starts (inline keys), given its entry and zone cookies' values. */
export function inlinePaths(pathAndSearch: string | null, entryCookie?: string, tzCookie?: string): string[] {
  if (!pathAndSearch) return [];
  const u = new URL(pathAndSearch, "http://x");
  if (u.pathname !== "/" && u.pathname !== "/messages-pro") return [];
  const out = ["/auth/me", "/chatter/me"];
  if (u.pathname === "/messages-pro") {
    const s = entryScreen(u.pathname, u.search, null);
    if (s) out.push(bundlePath(screenKey(s)));
    return out.map(inlineKey);
  }
  out.push("/admin/settings/applied");
  const hint = parseDashboardEntry(decoded(entryCookie));
  const tz = hint?.tz ?? decoded(tzCookie);
  if (tz) {
    const s = entryScreen(u.pathname, u.search, { tz, weekStart: hint?.weekStart ?? "monday", grid: hint?.grid ?? true });
    if (s) out.push(bundlePath(screenKey(s)));
  }
  return out.map(inlineKey);
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
