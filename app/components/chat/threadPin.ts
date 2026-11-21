/**
 * The Thread's pin to its latest message: the pure decisions `useThreadPin`
 * performs. No DOM here; the hook reads the container and writes `scrollTop`.
 */

/** Within this many px of the bottom counts as "at the bottom". */
export const AT_BOTTOM_PX = 80;
/** The first load's auto-pin lets go after this long whatever happens, so a
 *  chat whose media never settles cannot keep yanking the view (fix #11). */
export const AUTO_PIN_BACKSTOP_MS = 5000;
/** The first load's re-pin poll period (60Hz). */
export const PIN_POLL_MS = 16;
/** The top sentinel's observer fires this far above the viewport (its rootMargin). */
export const SENTINEL_MARGIN_PX = 200;
/** At most this many older pages load while the first load still pins (OF serves ~2 rows a page). */
export const MAX_FILL_PAGES = 4;

/** A scroll container's geometry, as read off the element. */
export interface Scroll { scrollHeight: number; scrollTop: number; clientHeight: number }

/** Px between the viewport's bottom edge and the content's. */
export function distanceFromBottom({ scrollHeight, scrollTop, clientHeight }: Scroll): number {
  return scrollHeight - scrollTop - clientHeight;
}

/** Strictly inside the AT_BOTTOM_PX band counts as at the bottom: 79 is, 80 is not. */
export function atBottom(distance: number): boolean {
  return distance < AT_BOTTOM_PX;
}

/** What a render does to the scroll position. `initial`: the first non-empty
 *  paint, hard-pinned and auto-pinned until released. `pin`: stick to the
 *  bottom (the snapshot was at the bottom, or there is none yet). `anchor`:
 *  older rows came in at the top, keep the same message in view at `top`.
 *  `none`: leave it. */
export type AfterRender =
  | { kind: "initial" }
  | { kind: "pin" }
  | { kind: "anchor"; top: number }
  | { kind: "none" };

/** `pre` is the geometry before the commit (the DOM still showed the old
 *  list), `scrollHeight` after it. Only a prepend (`prepended`) anchors: an
 *  append while scrolled up also grows scrollHeight, and anchoring it would
 *  push the view down one bubble per incoming message. */
export function afterRender({ prevLen, len, pre, scrollHeight, prepended }: {
  prevLen: number;
  len: number;
  pre: Scroll | null;
  scrollHeight: number;
  prepended: boolean;
}): AfterRender {
  if (prevLen === 0 && len > 0) return { kind: "initial" };
  if (!pre || atBottom(distanceFromBottom(pre))) return { kind: "pin" };
  if (prepended) {
    const delta = scrollHeight - pre.scrollHeight;
    if (delta > 0) return { kind: "anchor", top: pre.scrollTop + delta };
  }
  return { kind: "none" };
}

/** The oldest real (positive) id, or null. */
function firstPositiveId(list: readonly { id: number | string }[]): number | null {
  for (const m of list) {
    const n = Number(m.id);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return null;
}

/** Rows came in above the old top row (an older page, a seed page): the old
 *  first row now sits lower, or (it was dropped) the oldest real id went
 *  down. An append, an in-place patch or a removal at the tail is not one. */
export function rowsPrepended(
  prev: readonly { id: number | string }[],
  next: readonly { id: number | string }[],
): boolean {
  if (prev.length === 0 || next.length === 0) return false;
  const top = String(prev[0].id);
  if (String(next[0].id) === top) return false;
  if (next.some((m) => String(m.id) === top)) return true;
  const a = firstPositiveId(prev), b = firstPositiveId(next);
  return a != null && b != null && b < a;
}

export interface Point { x: number; y: number }

/** A finger releases the auto-pin only once it moves more up/down than
 *  sideways: a sideways swipe (the Thread's swipe back, kept or cancelled) is
 *  not a scroll. Without a start or a current point it releases. */
export function touchReleases(t0: Point | null, t: Point | null): boolean {
  return !(t0 && t && Math.abs(t.y - t0.y) <= Math.abs(t.x - t0.x));
}

/** A `scroll` event. `programmatic`: our own pin write emitted it (the flag set
 *  right before the write), so it never releases. Any other scroll that lands
 *  more than AT_BOTTOM_PX from the bottom while the auto-pin holds is the
 *  user's (scrollbar drag, gutter click, momentum fling) and releases it.
 *  `showJump`: the "↓ Latest" button, from AT_BOTTOM_PX * 4 up. Exactly 80px
 *  is neither at-bottom (`<`) nor a release (`>`), kept from main. */
export function onScrollDecision({ programmatic, pending, distance }: {
  programmatic: boolean;
  pending: boolean;
  distance: number;
}): { release: boolean; showJump: boolean } {
  const showJump = distance > AT_BOTTOM_PX * 4;
  if (programmatic) return { release: false, showJump };
  return { release: pending && distance > AT_BOTTOM_PX, showJump };
}

/** The top sentinel's IntersectionObserver loads an older page. Not while
 *  a page is already loading, nor after the last page failed (`failed`: only
 *  the Retry button loads then, no hot loop). While the first load is still
 *  pinning (`pending`) only once OF's head page has settled (`headSettled`:
 *  before that the sentinel is trivially visible on a seed's first paint and
 *  the cursor isn't OF's), and at most MAX_FILL_PAGES times (`fills`): a
 *  3-row chat that leaves the sentinel in view fills itself at once instead
 *  of sitting out the 5s backstop, and rows that render no height can't walk
 *  the whole history. */
export function mayLoadOlder({
  pending, headSettled = false, fills = 0, intersecting, hasOlder, loadingOlder, failed = false,
}: {
  pending: boolean;
  headSettled?: boolean;
  fills?: number;
  intersecting: boolean;
  hasOlder: boolean;
  loadingOlder: boolean;
  failed?: boolean;
}): boolean {
  if (!intersecting || !hasOlder || loadingOlder || failed) return false;
  return !pending || (headSettled && fills < MAX_FILL_PAGES);
}
