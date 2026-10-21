/**
 * The newest desktop shell build, as /download offers it. On a release bump all three together: desktop/package.json
 * "version", app/public/download.html (a static page outside the bundle, so its "v0.2.2" is not importable) and this.
 */
export const LATEST_DESKTOP_VERSION = "0.2.2";

/** True when `version` ("0.2.0", "v0.2.0", "0.2.0-beta.1") is a lower major.minor.patch than `latest`. An
 *  unreadable version (the shell's "unknown", a missing one) is never older: no banner on a guess. */
export function isOlderVersion(version: string | null | undefined, latest: string): boolean {
  const a = parse(version);
  const b = parse(latest);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i];
  return false;
}

function parse(v: string | null | undefined): [number, number, number] | null {
  const m = /^v?(\d+)\.(\d+)\.(\d+)/.exec(v?.trim() ?? "");
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}
