export function localPath(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return null;
  // browsers read "/\" as "//" and strip tabs/newlines before parsing
  return /[\\\u0000-\u001f\u007f]/.test(raw) ? null : raw;
}

export function nextHref(query: string | null | undefined, fallback?: string): string {
  return localPath(query) ?? localPath(fallback) ?? "/";
}
