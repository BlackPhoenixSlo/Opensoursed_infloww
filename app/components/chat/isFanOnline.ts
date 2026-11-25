import type { OFChatItem } from "@/lib/relay";

const ONLINE_WINDOW_MS = 5 * 60_000;

export type Seen = { lastSeen?: string | null };

export function isFanOnline(
  row: OFChatItem | undefined,
  profile: Seen | undefined,
  // Fan ids as text: a Fansly snowflake exceeds 2^53.
  onlineIds?: ReadonlySet<string>,
): boolean {
  if (row?.isOnline) return true;
  if (row && onlineIds?.has(String(row.withUser.id))) return true;
  const seen = newestSeen(row, profile);
  return seen != null && Date.now() - Date.parse(seen) < ONLINE_WINDOW_MS;
}

export function newestSeen(row: OFChatItem | undefined, profile: Seen | undefined): string | null {
  let newest: string | null = null;
  for (const iso of [(row?.withUser as Seen | undefined)?.lastSeen, profile?.lastSeen]) {
    const t = iso ? Date.parse(iso) : NaN;
    if (!Number.isNaN(t) && (newest == null || t > Date.parse(newest))) newest = iso!;
  }
  return newest;
}
