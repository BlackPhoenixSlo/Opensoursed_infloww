"use client";


import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

const PAGE = 12;

export interface OFPostMedia {
  id: number;
  type?: string;
  canView?: boolean;
  thumb?: string | null;
  preview?: string | null;
  squarePreview?: string | null;
  full?: string | null;
  source?: { source?: string | null } | null;
  files?: {
    preview?: { url?: string | null } | null;
    thumb?: { url?: string | null } | null;
  } | null;
}

export interface OFPost {
  id: number;
  text?: string;
  rawText?: string;
  price?: number | string | null;
  postedAt?: string;
  postedAtPrecise?: string;
  likesCount?: number;
  favoritesCount?: number;
  commentsCount?: number;
  tipsAmount?: string;
  mediaCount?: number;
  isPinned?: boolean;
  media?: OFPostMedia[];
  // OF's post detail uses `previews`, some list payloads `preview`; tolerate both.
  previews?: number[];
  preview?: number[];
}

interface PostsPage {
  posts: OFPost[];
  hasMore: boolean;
}

function normalize(raw: unknown): OFPost[] {
  if (Array.isArray(raw)) return raw as OFPost[];
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    if (Array.isArray(o.list)) return o.list as OFPost[];
    if (Array.isArray(o.posts)) return o.posts as OFPost[];
  }
  return [];
}

export function usePosts(accountId: string | null) {
  return useInfiniteQuery<PostsPage>({
    queryKey: ["my-posts", accountId],
    enabled: !!accountId,
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.hasMore ? all.length * PAGE : undefined),
    queryFn: async ({ pageParam, signal }) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE));
      params.set("offset", String(pageParam ?? 0));
      const raw = await relay.get<unknown>(
        `/api/of/v2/posts?${params.toString()}`,
        { accountId: accountId ?? undefined },
        signal,
      );
      const posts = normalize(raw);
      return { posts, hasMore: posts.length >= PAGE };
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export type FeedMediaType = "all" | "photo" | "video";

interface FeedPage {
  posts: OFPost[];
  hasMore: boolean;
  nextCursor: string | null;
}

export function useMyFeed(accountId: string | null, type: FeedMediaType = "all") {
  return useInfiniteQuery<FeedPage>({
    queryKey: ["my-feed", accountId, type],
    enabled: !!accountId,
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    queryFn: async ({ pageParam, signal }) => {
      const params = new URLSearchParams();
      params.set("limit", "24");
      params.set("format", "infinite");
      if (type !== "all") params.set("type", type);
      if (pageParam) params.set("before_publish_time", String(pageParam));
      const raw = await relay.get<unknown>(
        `/api/of/v2/users/${encodeURIComponent(accountId!)}/posts?${params.toString()}`,
        { accountId: accountId ?? undefined },
        signal,
      );
      const posts = normalize(raw);
      const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
      // A missing marker would loop the same page forever.
      const tail = typeof o.tailMarker === "string" && o.tailMarker ? o.tailMarker : null;
      const hasMore = Boolean(o.hasMore) && posts.length > 0 && !!tail;
      return { posts, hasMore, nextCursor: hasMore ? tail : null };
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export type TopBy = "purchases" | "likes" | "comments" | "views";

export function useTopPosts(
  accountId: string | null,
  by: TopBy,
  from: string | null,
  to: string | null,
) {
  return useQuery<OFPost[]>({
    queryKey: ["top-posts", accountId, by, from, to],
    enabled: !!accountId,
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams();
      params.set("by", by);
      params.set("limit", "50");
      if (from) params.set("start", from);
      if (to) params.set("end", to);
      const raw = await relay.get<unknown>(
        `/api/of/v2/posts/top?${params.toString()}`,
        { accountId: accountId ?? undefined },
        signal,
      );
      return normalizeItems(raw);
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

function normalizeItems(raw: unknown): OFPost[] {
  if (Array.isArray(raw)) return raw as OFPost[];
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    if (Array.isArray(o.items)) return o.items as OFPost[];
    if (Array.isArray(o.list)) return o.list as OFPost[];
    if (Array.isArray(o.posts)) return o.posts as OFPost[];
  }
  return [];
}

export function postThumbUrl(m: OFPostMedia): string | null {
  return (
    m.squarePreview ||
    m.preview ||
    m.thumb ||
    m.files?.preview?.url ||
    m.files?.thumb?.url ||
    m.full ||
    m.source?.source ||
    null
  );
}

export function postPlainText(p: OFPost): string {
  const html = p.rawText ?? p.text ?? "";
  return html
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}
