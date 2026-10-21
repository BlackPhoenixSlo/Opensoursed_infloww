/**
 * The online rule (docs/spec/phase-01-window-chrome-tabs.md, Interfaces,
 * `isFanOnline`): the Fan counts as online when the chat row says so
 * (OnlyFans' `isOnline`), when the Fan was last seen less than 5 minutes ago
 * (the Clone's rule, messages.js:98-101), or when the Fan id is among
 * `onlineIds` (the Creator's online subscribers, read by Online Fans). A Fan
 * whose presence is unknown (no row, no `lastSeen`) is offline.
 */

import type { OFChatItem } from "@/lib/relay";

/** Less than this since `lastSeen` is online; exactly 5 minutes is not. */
const ONLINE_WINDOW_MS = 5 * 60_000;

/** `lastSeen` rides on the row's Fan once the chat list enriches it
 *  (`useChatList.ts`), and on the Fan's full profile (`useOFUser.ts`). */
export type Seen = { lastSeen?: string | null };

export function isFanOnline(
  row: OFChatItem | undefined,
  profile: Seen | undefined,
  /** Fan ids as text, the wire's spelling (a Fansly snowflake exceeds 2^53). */
  onlineIds?: ReadonlySet<string>,
): boolean {
  if (row?.isOnline) return true;
  if (row && onlineIds?.has(String(row.withUser.id))) return true;
  const seen = newestSeen(row, profile);
  return seen != null && Date.now() - Date.parse(seen) < ONLINE_WINDOW_MS;
}

/** The newer of the two `lastSeen` times the app knows (the row's Fan, the
 *  Fan's profile), or null when neither holds a readable time. */
export function newestSeen(row: OFChatItem | undefined, profile: Seen | undefined): string | null {
  let newest: string | null = null;
  for (const iso of [(row?.withUser as Seen | undefined)?.lastSeen, profile?.lastSeen]) {
    const t = iso ? Date.parse(iso) : NaN;
    if (!Number.isNaN(t) && (newest == null || t > Date.parse(newest))) newest = iso!;
  }
  return newest;
}
