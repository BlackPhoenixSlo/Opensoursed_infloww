import { persistJSON, readJSON } from "./persist";

import type { AuthedUserDTO } from "@/contexts/UserContext";

// `chatterly:` prefix is load-bearing: wipeIdentityStorage() sweeps it on every identity flip, so no snapshot outlives its principal.
const SNAPSHOT_KEY = "chatterly:auth-snapshot:v1";
const SNAPSHOT_TTL_MS = 3 * 24 * 60 * 60 * 1000;

interface AuthSnapshot {
  at: number;
  user: AuthedUserDTO;
}

export function readAuthSnapshot(): AuthedUserDTO | null {
  const parsed = readJSON<AuthSnapshot>(SNAPSHOT_KEY);
  if (!parsed || typeof parsed.at !== "number") return null;
  if (parsed.at < Date.now() - SNAPSHOT_TTL_MS) return null;
  const u = parsed.user;
  if (!u || typeof u.user_id !== "string" || !u.user_id) return null;
  // An overlay is never written; treat one as corrupt rather than paint it.
  if (u.impersonating) return null;
  return u;
}

export function writeAuthSnapshot(user: AuthedUserDTO | null): void {
  // Server-confirmed principals only; a stale impersonation overlay would misreport who the founder acts as.
  if (!user || !user.user_id || user.impersonating) {
    clearAuthSnapshot();
    return;
  }
  persistJSON(SNAPSHOT_KEY, { at: Date.now(), user } satisfies AuthSnapshot);
}

export function clearAuthSnapshot(): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(SNAPSHOT_KEY); } catch { }
}
