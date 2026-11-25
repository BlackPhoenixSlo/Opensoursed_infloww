import type { InlineAnswer, InlineData } from "@/lib/inlineBoot";
import { BOOTED, inlineKey } from "@/lib/inlineBoot";
import { bundlePath } from "@/lib/screenKey";
import { bootScreen, type CookieRead } from "@/lib/screenEntry";

export const INLINE_TIMEOUT_MS = 2_500;

export function inlinePaths(pathAndSearch: string | null, cookie: CookieRead): string[] {
  if (!pathAndSearch) return [];
  const { pathname } = new URL(pathAndSearch, "http://x");
  if (!BOOTED.has(pathname)) return [];
  const s = bootScreen(pathAndSearch, cookie);
  return ["/auth/me", "/chatter/me", ...(pathname === "/" ? ["/admin/settings/applied"] : []), ...(s ? [bundlePath(s)] : [])]
    .map(inlineKey);
}

export function startInline(paths: string[], cookie: string | null, relayUrl: string): InlineData | null {
  if (!cookie || !paths.length) return null;
  const base = relayUrl.replace(/\/+$/, "");
  const get = async (p: string): Promise<InlineAnswer> => {
    try {
      // Per-request promises, never cached or shared: one browser's answers must not land in another's HTML.
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
