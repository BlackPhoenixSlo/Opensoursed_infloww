/**
 * Where Landing goes after sign-in / sign-up: `?next=` only when it is a path on this host.
 * "/x" yes; "//evil", "/\evil", "https://…", "javascript:…", backslashes or control characters no
 * (browsers read "/\" and "\" as "//", and strip tabs/newlines before parsing).
 */
export function localPath(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return null;
  return /[\\\u0000-\u001f\u007f]/.test(raw) ? null : raw;
}

/** `?next=` if it is local, else the caller's own `next` if local, else the Dashboard. */
export function nextHref(query: string | null | undefined, fallback?: string): string {
  return localPath(query) ?? localPath(fallback) ?? "/";
}
