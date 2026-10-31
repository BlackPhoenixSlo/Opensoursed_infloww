/**
 * Emoji picker popover placement — pure. Opens below the trigger when the
 * preferred height fits there (or below has more room), else above; the
 * panel's edge follows the trigger's `align` side, clamped into the viewport.
 */

const PANEL_W = 384;
const PANEL_H_PREF = 400;
const MARGIN = 8;

export interface PopoverCoords {
  top?: number;
  bottom?: number;
  right?: number;
  left?: number;
  maxHeight: number;
}

/** `r` is the trigger's getBoundingClientRect(). */
export function placeEmojiPopover(
  r: Pick<DOMRect, "top" | "bottom" | "left" | "right">,
  viewport: { width: number; height: number },
  align: "left" | "right",
): PopoverCoords {
  const spaceAbove = r.top - MARGIN;
  const spaceBelow = viewport.height - r.bottom - MARGIN;
  const openDown = spaceBelow >= PANEL_H_PREF || spaceBelow > spaceAbove;
  const vert: { top?: number; bottom?: number; maxHeight: number } = openDown
    ? { top: r.bottom + MARGIN, maxHeight: Math.min(PANEL_H_PREF, spaceBelow) }
    : { bottom: viewport.height - r.top + MARGIN, maxHeight: Math.min(PANEL_H_PREF, spaceAbove) };
  if (align === "right") {
    const wantRight = viewport.width - r.right;
    const maxRight = viewport.width - PANEL_W - MARGIN;
    return { ...vert, right: Math.max(MARGIN, Math.min(wantRight, maxRight)) };
  }
  const wantLeft = r.left;
  const maxLeft = viewport.width - PANEL_W - MARGIN;
  return { ...vert, left: Math.max(MARGIN, Math.min(wantLeft, maxLeft)) };
}
