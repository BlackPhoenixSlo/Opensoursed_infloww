import type { GiphyItem, GiphyResponse } from "@/lib/relay";

export const PAGE_SIZE = 24;

export interface GifState {
  items: GiphyItem[];
  loading: boolean;
  error: string | null;
  hasMore: boolean;
}

export type GifAction =
  | { type: "start" }
  | { type: "loaded"; resp: GiphyResponse; offset: number }
  | { type: "failed"; message: string; offset: number };

export const INITIAL_GIFS: GifState = { items: [], loading: false, error: null, hasMore: false };

export function hasMoreAfter(resp: GiphyResponse, offset: number): boolean {
  return (resp.data?.length ?? 0) >= PAGE_SIZE && offset + PAGE_SIZE < (resp.pagination?.total_count ?? 0);
}

export function gifReducer(s: GifState, a: GifAction): GifState {
  switch (a.type) {
    case "start":
      return { ...s, loading: true, error: null };
    case "loaded": {
      const page = a.resp.data || [];
      const at = a.resp.pagination?.offset ?? a.offset;
      return {
        items: a.offset === 0 ? page : [...s.items, ...page],
        loading: false, error: null, hasMore: hasMoreAfter(a.resp, at),
      };
    }
    case "failed":
      return a.offset === 0
        ? { items: [], loading: false, error: a.message, hasMore: false }
        : { ...s, loading: false, error: a.message };
  }
}
