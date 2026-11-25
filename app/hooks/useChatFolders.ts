"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useCan } from "@/hooks/useCan";
import { relay } from "@/lib/relay";

export interface ChatFolder {
  id: number | string;
  name?: string;
  type?: string;
  isPinnedToChat?: boolean;
  canPinnedToChat?: boolean;
  usersCount?: number;
  subscribersCount?: number;
  canAddUsers?: boolean;
  canManageUsers?: boolean;
  users?: Array<{ id: number }>;
}

interface FoldersResp {
  list?: ChatFolder[];
  hasMore?: boolean;
}

// trailing "all" is vestigial but kept so existing browsers re-hydrate their persisted folder list; invalidators match the prefix
const FOLDERS_KEY = (accountId: string | null) =>
  ["chat-folders", accountId ?? "", "all"] as const;

const selectPinned = (rows: ChatFolder[]): ChatFolder[] =>
  rows.filter((f) => f.isPinnedToChat);

function useFolders(
  accountId: string | null,
  select?: (rows: ChatFolder[]) => ChatFolder[],
) {
  const allowed = useCan(accountId, "filter_folders");
  return useQuery({
    queryKey: FOLDERS_KEY(accountId),
    enabled: !!accountId && allowed,
    staleTime: 60_000,
    select,
    queryFn: async (): Promise<ChatFolder[]> => {
      if (!accountId) return [];
      const r = await relay.get<FoldersResp>(
        `/api/of/v2/chats/folders?limit=50`,
        { accountId },
      );
      const list = r.list ?? [];
      return list.slice().sort((a, b) => {
        const ap = a.isPinnedToChat ? 1 : 0;
        const bp = b.isPinnedToChat ? 1 : 0;
        if (ap !== bp) return bp - ap;
        return (a.name || "").localeCompare(b.name || "");
      });
    },
  });
}

export function useAllChatFolders(accountId: string | null) {
  return useFolders(accountId);
}

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
