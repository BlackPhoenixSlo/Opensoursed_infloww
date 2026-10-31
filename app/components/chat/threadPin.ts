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
 *  bottom (the snapshot was at the bottom, or there is none yet). `anchor`: an
 *  older page came in at the top, keep the same message in view at `top`.
 *  `none`: leave it. */
export type AfterRender =
  | { kind: "initial" }
  | { kind: "pin" }
  | { kind: "anchor"; top: number }
  | { kind: "none" };

export function afterRender({ prevLen, len, pre, scrollHeight }: {
  prevLen: number;
  len: number;
  pre: Scroll | null;
  scrollHeight: number;
}): AfterRender {
  if (prevLen === 0 && len > 0) return { kind: "initial" };
  if (!pre || atBottom(distanceFromBottom(pre))) return { kind: "pin" };
  if (len > prevLen) {
    const delta = scrollHeight - pre.scrollHeight;
    if (delta > 0) return { kind: "anchor", top: pre.scrollTop + delta };
  }
  return { kind: "none" };
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

/** The top sentinel's IntersectionObserver loads an older page: never while
 *  the first load is still pinning (the sentinel is trivially visible on the
 *  first paint), nor while a page is already loading. */
export function mayLoadOlder({ pending, intersecting, hasOlder, loadingOlder }: {
  pending: boolean;
  intersecting: boolean;
  hasOlder: boolean;
  loadingOlder: boolean;
}): boolean {
  return !pending && intersecting && hasOlder && !loadingOlder;
}
