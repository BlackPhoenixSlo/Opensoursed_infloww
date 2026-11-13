/**
 * The thread's load-older pager for ONE chat: a pure reducer useChatMessages
 * only dispatches to, plus the reads its consumers take off it.
 *
 *   idle      — more history may exist; the top sentinel may auto-load.
 *   loading   — one older page in flight (`seq` names it; a page or failure
 *               for any other seq is a stale answer and changes nothing).
 *   error     — the last page failed, timed out, or came back without
 *               progress while still claiming `hasMore`. Auto-load stops (a
 *               failure or a stuck cursor must not re-fire in a hot loop);
 *               only an explicit call (the Retry button, a search) loads.
 *   exhausted — OF said nothing older. Sticky for the chat: a head poll's
 *               `hasMore: true` never reopens it (that flag is about the
 *               rows below the HEAD page, which this chat already has).
 *
 * A new chat starts a new pager (`initialOlderPager`).
 */

/** Client deadline for one older page: past it the request is aborted and the
 *  pager shows Retry instead of a "Loading older…" that never ends. */
export const OLDER_TIMEOUT_MS = 15_000;

export type OlderPager =
  | { status: "idle" }
  | { status: "loading"; seq: number }
  | { status: "error" }
  | { status: "exhausted" };

export type OlderPagerAction =
  | { type: "start"; seq: number }
  /** An older page landed. `progressed`: its oldest id is below the cursor it
   *  was asked with. */
  | { type: "page"; seq: number; hasMore: boolean; progressed: boolean }
  | { type: "fail"; seq: number }
  /** A head (newest) page landed: only its "nothing older" counts. */
  | { type: "head"; hasMore: boolean };

const IDLE: OlderPager = { status: "idle" };
const ERROR: OlderPager = { status: "error" };
const EXHAUSTED: OlderPager = { status: "exhausted" };

/** A chat's first pager: exhausted when its last head page (a prefetch's) said
 *  nothing older, else idle so the first scroll-up can ask. */
export function initialOlderPager(headSaysNoMore = false): OlderPager {
  return headSaysNoMore ? EXHAUSTED : IDLE;
}

export function olderPagerReducer(state: OlderPager, action: OlderPagerAction): OlderPager {
  switch (action.type) {
    case "start":
      return state.status === "idle" || state.status === "error" ? { status: "loading", seq: action.seq } : state;
    case "page":
      if (state.status !== "loading" || state.seq !== action.seq) return state;
      if (!action.hasMore) return EXHAUSTED;
      return action.progressed ? IDLE : ERROR;
    case "fail":
      return state.status === "loading" && state.seq === action.seq ? ERROR : state;
    case "head":
      return action.hasMore || state.status === "exhausted" ? state : EXHAUSTED;
  }
}

/** The "Load older" button / sentinel exist at all. */
export const hasOlder = (s: OlderPager): boolean => s.status !== "exhausted";
export const isLoadingOlder = (s: OlderPager): boolean => s.status === "loading";
/** Auto-load paused: the button reads Retry. */
export const olderFailed = (s: OlderPager): boolean => s.status === "error";
/** An explicit call (a click, Retry, a search) may start a page. */
export const canLoadOlder = (s: OlderPager): boolean => s.status === "idle" || s.status === "error";
