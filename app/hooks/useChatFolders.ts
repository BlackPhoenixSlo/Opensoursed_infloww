"use client";

/**
 * useChatFolders — fetch the model account's pinnable fan-lists so the
 * inbox can render them as folder chips (a folder icon, then the list
 * name). Mirrors the legacy /ui/ behaviour: only the lists already
 * pinned to chat appear as chips; the pencil ("Pin lists as chips") opens the full list
 * (pinned + unpinned) and lets the user toggle.
 *
 * Only fires in single-account scope. Unified mode has no single "my
 * pinned folders" since each account has its own — we hide the strip
 * there.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { OF_CHAT_FOLDERS, readAllListPages, type ListPage } from "@/lib/ofListPages";

export interface ChatFolder {
  id: number | string;
  name?: string;
  /** OF list type: "custom" / "close_friends" (user-modifiable) or a system
   *  bucket ("following"/"fans"/"recent"/…). */
  type?: string;
  /** OF's flag — true means this list shows up as a sidebar chip. */
  isPinnedToChat?: boolean;
  /** OF's flag — the list may be pinned to the chats sidebar at all. */
  canPinnedToChat?: boolean;
  usersCount?: number;
  subscribersCount?: number;
  /** true when the operator may add/remove users on this list (custom +
   *  close-friends); system buckets report false. */
  canAddUsers?: boolean;
  canManageUsers?: boolean;
  /** A CAPPED preview of members (OF returns only the first few) — used for
   *  best-effort membership display in the "Add to list" menu. */
  users?: Array<{ id: number }>;
}

// ONE query key for the folder list, two views of it.
//
// The pinned chips (ChatList) and the full picker (AvatarMenu) both mount on the inbox and both want the same upstream
// `/chats/folders` resource. Under two query keys that was two OF calls on
// every inbox open — the pinned set is just a filter of the full one, so it is
// now derived with `select` off the shared key and costs nothing.
//
// The one `select` fn is module-level so its identity is stable across
// renders (an inline fn would re-run it every render and defeat react-query's
// memoisation). The picker passes none at all — no-`select` already returns
// the rows untouched, so an identity fn would be pure indirection.
//
// Version the complete result so persisted first-page-only caches cannot hide lists.
// Invalidators match the ["chat-folders", accountId] prefix and reach every page.
const FOLDERS_KEY = (accountId: string | null) =>
  ["chat-folders", accountId ?? "", "all", "all-pages"] as const;

const selectPinned = (rows: ChatFolder[]): ChatFolder[] =>
  rows.filter((f) => f.isPinnedToChat);

function useFolders(
  accountId: string | null,
  select?: (rows: ChatFolder[]) => ChatFolder[],
) {
  return useQuery({
    queryKey: FOLDERS_KEY(accountId),
    enabled: !!accountId,
    staleTime: 60_000, // #12/#25: was 3 days — refresh folder/VIP membership actively
    select,
    queryFn: async ({ signal }): Promise<ChatFolder[]> => {
      if (!accountId) return [];
      const list = await readAllListPages(
        (path) => relay.get<ListPage<ChatFolder>>(path, { accountId }, signal),
        OF_CHAT_FOLDERS,
      );
      // Pinned-first, then alpha. Matches /ui/ ordering.
      return list.slice().sort((a, b) => {
        const ap = a.isPinnedToChat ? 1 : 0;
        const bp = b.isPinnedToChat ? 1 : 0;
        if (ap !== bp) return bp - ap;
        return (a.name || "").localeCompare(b.name || "");
      });
    },
  });
}

/** All pinnable lists (both pinned + not) — used by the picker. */
export function useAllChatFolders(accountId: string | null) {
  return useFolders(accountId);
}

/** Only the lists currently pinned — these render as chips. Same fetch as
 *  `useAllChatFolders`; the chips now inherit that call's alpha ordering
 *  instead of OF's raw list order. */
export function useChatFolders(accountId: string | null) {
  return useFolders(accountId, selectPinned);
}

export function usePinChatFolder(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { listId: number | string; pinned: boolean }) => {
      if (!accountId) throw new Error("no account in scope");
      return relay.patch(
        `/api/of/v2/lists/${encodeURIComponent(String(vars.listId))}/pin-chat`,
        { pinned: vars.pinned },
        { accountId },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chat-folders", accountId ?? ""] });
    },
  });
}
