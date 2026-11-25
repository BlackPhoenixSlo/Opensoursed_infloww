export const AT_BOTTOM_PX = 80;
// Releases after this whatever happens, so a chat whose media never settles cannot keep yanking the view.
export const AUTO_PIN_BACKSTOP_MS = 5000;
export const PIN_POLL_MS = 16;
export const SENTINEL_MARGIN_PX = 200;
// OF serves ~2 rows a page.
export const MAX_FILL_PAGES = 4;

export interface Scroll { scrollHeight: number; scrollTop: number; clientHeight: number }

export function distanceFromBottom({ scrollHeight, scrollTop, clientHeight }: Scroll): number {
  return scrollHeight - scrollTop - clientHeight;
}

export function atBottom(distance: number): boolean {
  return distance < AT_BOTTOM_PX;
}

export type AfterRender =
  | { kind: "initial" }
  | { kind: "pin" }
  | { kind: "anchor"; top: number }
  | { kind: "none" };

// Only a prepend anchors: an append while scrolled up also grows scrollHeight and would push the view down per message.
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

function firstPositiveId(list: readonly { id: number | string }[]): number | null {
  for (const m of list) {
    const n = Number(m.id);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return null;
}

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

export function touchReleases(t0: Point | null, t: Point | null): boolean {
  return !(t0 && t && Math.abs(t.y - t0.y) <= Math.abs(t.x - t0.x));
}

// Exactly 80px is neither at-bottom nor a release.
export function onScrollDecision({ programmatic, pending, distance }: {
  programmatic: boolean;
  pending: boolean;
  distance: number;
}): { release: boolean; showJump: boolean } {
  const showJump = distance > AT_BOTTOM_PX * 4;
  if (programmatic) return { release: false, showJump };
  return { release: pending && distance > AT_BOTTOM_PX, showJump };
}

// While pinning, wait for OF's head page (`headSettled`): the sentinel is trivially visible on a seed's first paint.
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
