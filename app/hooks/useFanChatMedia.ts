"use client";


import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { useCan } from "@/hooks/useCan";

export interface FanChatMediaItem {
  id: number;
  text: string;
  // OF returns dollars as a float; 0 means free.
  price: number;
  isFree: boolean;
  isOpened: boolean;
  isFromQueue: boolean;
  mediaCount: number;
  createdAt: string;
  fromUser?: { id: number };
  media: Array<{
    id: number;
    type: "photo" | "video" | "gif" | "audio" | string;
    duration?: number;
    files?: {
      full?: { url?: string | null } | null;
      thumb?: { url?: string | null } | null;
      preview?: { url?: string | null } | null;
      squarePreview?: { url?: string | null } | null;
    };
  }>;
}

export interface FanChatMediaPage {
  list: FanChatMediaItem[];
  // OF returns it as a string id; the relay passes it through verbatim.
  nextLastId?: string | number | null;
  hasMore?: boolean;
}

export type ChatMediaKind = "photos" | "videos" | "audios";

export function useFanChatMedia(
  accountId: string | null,
  fanId: FanId | null,
  opts: {
    purchased?: boolean;
    creatorOnly?: boolean;
    limit?: number;
    enabled?: boolean;
    kind?: ChatMediaKind;
    opened?: boolean;
  } = {},
) {
  const purchased = opts.purchased ?? true;
  const { kind, opened = false } = opts;
  const creatorOnly = opts.creatorOnly ?? true;
  const limit = opts.limit ?? 20;
  const allowed = useCan(accountId, "chat_media");
  const enabled = (opts.enabled ?? true) && !!accountId && fanId != null && allowed;
  return useInfiniteQuery<FanChatMediaPage>({
    queryKey: ["fan-chat-media", accountId, fanId, purchased, limit, creatorOnly, ...(kind ? [kind] : []), ...(opened ? ["opened"] : [])] as const,
    enabled,
    initialPageParam: null as string | number | null,
    queryFn: ({ pageParam, signal }) => {
      const qs = new URLSearchParams();
      qs.set("limit", String(limit));
      qs.set("skip_users", "all");
      // Without from_user OF returns both directions, incl. the fan's own attachments.
      if (creatorOnly && accountId) qs.set("from_user", accountId);
      if (purchased) {
        qs.set("purchased", "1");
      }
      if (opened) qs.set("opened", "1");
      if (pageParam != null) qs.set("last_id", String(pageParam));
      return relay.get<FanChatMediaPage>(
        // The gallery type tab is a PATH segment, not a query param.
        `/api/of/v2/chats/${fanId}/media${kind ? `/${kind}` : ""}?${qs.toString()}`,
        { accountId, priority: "background" },
        signal,
      );
    },
    getNextPageParam: (lastPage) =>
      lastPage.hasMore && lastPage.nextLastId != null
        ? lastPage.nextLastId
        : undefined,
    // Slow call (3-9s through OF); a fan unlocks at most about once a day.
    staleTime: 30 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
    maxPages: 20,
  });
}
