export const OLDER_TIMEOUT_MS = 15_000;

export type OlderPager = (
  | { status: "idle" }
  | { status: "loading"; seq: number }
  | { status: "error" }
  | { status: "exhausted" }
) & { headSettled: boolean };

export type OlderPagerAction =
  | { type: "start"; seq: number }
  | { type: "page"; seq: number; hasMore: boolean; progressed: boolean }
  | { type: "fail"; seq: number }
  | { type: "head"; hasMore: boolean; settled: boolean };

export function initialOlderPager(headSaysNoMore = false): OlderPager {
  return { status: headSaysNoMore ? "exhausted" : "idle", headSettled: false };
}

export function olderPagerReducer(state: OlderPager, action: OlderPagerAction): OlderPager {
  const { headSettled } = state;
  switch (action.type) {
    case "start":
      return state.status === "idle" || state.status === "error" ? { status: "loading", seq: action.seq, headSettled } : state;
    case "page":
      if (state.status !== "loading" || state.seq !== action.seq) return state;
      if (!action.hasMore) return { status: "exhausted", headSettled };
      return { status: action.progressed ? "idle" : "error", headSettled };
    case "fail":
      return state.status === "loading" && state.seq === action.seq ? { status: "error", headSettled } : state;
    case "head": {
      const exhaust = !action.hasMore && state.status !== "exhausted";
      const settle = action.settled && !headSettled;
      if (!exhaust && !settle) return state;
      return exhaust ? { status: "exhausted", headSettled: headSettled || action.settled } : { ...state, headSettled: true };
    }
  }
}

export const hasOlder = (s: OlderPager): boolean => s.status !== "exhausted";
export const isLoadingOlder = (s: OlderPager): boolean => s.status === "loading";
export const olderFailed = (s: OlderPager): boolean => s.status === "error";
export const canLoadOlder = (s: OlderPager): boolean => s.status === "idle" || s.status === "error";
