import type { AccountMeta } from "@/lib/relay";

export interface Connectivity {
  label: string;
  title?: string;
  tone: "ok" | "err" | "muted";
  dead?: boolean;
}

export function sessionConnectivity(a: Pick<AccountMeta, "session_dead_at" | "has_session" | "is_active">): Connectivity | null {
  if (a.session_dead_at) return { label: "Disconnected", tone: "err", dead: true };
  if (!a.has_session) return { label: "Not connected", tone: "muted" };
  if (!a.is_active) return { label: "—", title: "deactivated: not probed", tone: "muted" };
  return null;
}

export const liveSession = (a: Pick<AccountMeta, "has_session" | "session_dead_at">) => !!a.has_session && !a.session_dead_at;
