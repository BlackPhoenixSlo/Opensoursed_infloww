// On a release bump change desktop/package.json, app/public/download.html (static, not importable) and this together.
export const LATEST_DESKTOP_VERSION = "0.2.5";

export function isOlderVersion(version: string | null | undefined, latest: string): boolean {
  const a = parse(version);
  const b = parse(latest);
  // An unreadable version is never older: no banner on a guess.
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i];
  return false;
}

function parse(v: string | null | undefined): [number, number, number] | null {
  const m = /^v?(\d+)\.(\d+)\.(\d+)/.exec(v?.trim() ?? "");
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}
