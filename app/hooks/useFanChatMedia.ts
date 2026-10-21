"use client";

/**
 * useFanChatMedia — OF's per-fan media gallery, cursor-paginated.
 *
 * Backed by GET /api/of/v2/chats/{fanId}/media (proxied to OF's
 * /chats/{chat_id}/media). With `opened=1, skip_users=all` the response
 * mirrors OF web's "Purchased" tab in the fan profile — every PPV the
 * fan has paid for, with thumbnails, the original message text (HTML),
 * price, and timestamp.
 *
 * Why this exists: the Phase F /payouts/transactions ingest fills the
 * ledger with historical PPV rows that DON'T carry the originating
 * message_id, so joining transactions→messages by id loses body/media
 * for long-tenure fans. This endpoint is the only source that gives us
 * thumbnails + text for those rows. The frontend then fuzzy-matches
 * (price ≈ amount, nearest createdAt wins) to enrich each ledger entry.
 *
 * Pagination: OF returns `nextLastId` (string id of the oldest item in
 * the page); pass it back as `last_id=<id>` to get the next page.
 * `useInfiniteQuery` accumulates pages; the consumer flattens
 * `data.pages.flatMap(p => p.list)`.
 */

import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface FanChatMediaItem {
  /** OF's message id. */
  id: number;
  /** HTML — needs to be stripped (`<br>` → \n, `</p><p>` → \n,
   *  then strip remaining tags) before rendering as preview text. */
  text: string;
  /** OF returns dollars as a float; 0 means free. */
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
  /** Cursor for the next page — feed back as `last_id` to keep paging.
   *  OF returns it as a string id; we accept either since the relay
   *  passes it through verbatim. */
  nextLastId?: string | number | null;
  hasMore?: boolean;
}

/** OF's chat gallery type tabs (Photos, Videos, Audio): the media path's last segment. */
export type ChatMediaKind = "photos" | "videos" | "audios";

export function useFanChatMedia(
  accountId: string | null,
  fanId: FanId | null,
  opts: {
    purchased?: boolean;
    creatorOnly?: boolean;
    limit?: number;
    enabled?: boolean;
    /** OF's gallery type tab, a PATH segment (`/media/photos`; its web app's chats-gallery, module 204607 `L`). */
    kind?: ChatMediaKind;
    /** OF's Unlocked tab (`opened=1`): the media the fan has viewed, free ones included. */
    opened?: boolean;
  } = {},
) {
  const purchased = opts.purchased ?? true;
  const { kind, opened = false } = opts;
  // `false` asks for both directions (the Chat gallery, ticket 88); the
  // default keeps every other caller on the Creator's own media.
  const creatorOnly = opts.creatorOnly ?? true;
  const limit = opts.limit ?? 20;
  const enabled = (opts.enabled ?? true) && !!accountId && fanId != null;
  return useInfiniteQuery<FanChatMediaPage>({
    // Include `purchased` and `creatorOnly` in the key so flipping either
    // forces a fresh fetch instead of serving another list's cache.
    // A type tab or Unlocked extends the key; every other caller's key stays as it was.
    queryKey: ["fan-chat-media", accountId, fanId, purchased, limit, creatorOnly, ...(kind ? [kind] : []), ...(opened ? ["opened"] : [])] as const,
    enabled,
    initialPageParam: null as string | number | null,
    queryFn: ({ pageParam, signal }) => {
      const qs = new URLSearchParams();
      qs.set("limit", String(limit));
      qs.set("skip_users", "all");
      // Pin to creator-sent only unless `creatorOnly` is false (accountId
      // IS the creator's OF user id). Without this OF returns BOTH
      // directions, including the fan's own attachments — meaningless for
      // the "Sales" and "unsold PPVs" feeds, wanted by the Chat gallery.
      if (creatorOnly && accountId) qs.set("from_user", accountId);
      if (purchased) {
        // Matches OF web's /my/chats/chat/{id}/gallery/purchased call.
        qs.set("purchased", "1");
      }
      if (opened) qs.set("opened", "1");
      if (pageParam != null) qs.set("last_id", String(pageParam));
      return relay.get<FanChatMediaPage>(
        `/api/of/v2/chats/${fanId}/media${kind ? `/${kind}` : ""}?${qs.toString()}`,
        // accountId in ctx → X-Account-Id header so the relay routes
        // through the right account's OFClient. "background" priority
        // means this never queues ahead of user-initiated work.
        { accountId, priority: "background" },
        signal,
      );
    },
    getNextPageParam: (lastPage) =>
      lastPage.hasMore && lastPage.nextLastId != null
        ? lastPage.nextLastId
        : undefined,
    // OF gallery doesn't change often (a fan unlocks once a day at most)
    // AND this call is slow (3-9s relay round-trip through OF). SWR
    // window: cached data is "fresh" for 30 min, after which the next
    // mount serves it instantly AND kicks a background refetch — React
    // Query's default stale behavior. gcTime: 1 day so the cache
    // survives the drawer being closed and re-opened across a session.
    // Pair with the localStorage persister allowlist entry for
    // `fan-chat-media` so the cache also survives tab reload / popout.
    staleTime: 30 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
    // Memory cap — at limit=20 that's 400 items, plenty for any single fan.
    maxPages: 20,
  });
}
