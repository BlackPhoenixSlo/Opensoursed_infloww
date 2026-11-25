import type { Screen } from "@/lib/screenKey";

const SCOPE_COOKIE = "chatterly_scope";
const YEAR_S = 365 * 24 * 3600;

export type CookieRead = (name: string) => string | undefined;

export function bootScreen(pathAndSearch: string, cookie: CookieRead): Screen | null {
  const u = new URL(pathAndSearch, "http://x");
  if (u.pathname === "/messages-pro") return cookie(SCOPE_COOKIE) === "model" ? null : { kind: "inbox", cursor: 0 };
  return null;
}

export function cookieValue(cookies: string, name: string): string | undefined {
  const hit = cookies.split("; ").find((c) => c.startsWith(`${name}=`));
  if (hit == null) return undefined;
  try {
    return decodeURIComponent(hit.slice(name.length + 1));
  } catch {
    return undefined;
  }
}

function writeCookie(name: string, value: string | null): void {
  try {
    document.cookie = `${name}=${encodeURIComponent(value ?? "")}; path=/; max-age=${value == null ? 0 : YEAR_S}; samesite=lax`;
  } catch { }
}

export function rememberScope(one: boolean): void {
  writeCookie(SCOPE_COOKIE, one ? "model" : "all");
}

export function forgetScope(): void {
  writeCookie(SCOPE_COOKIE, null);
}
