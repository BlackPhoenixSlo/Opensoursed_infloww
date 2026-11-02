/**
 * anchorPanel — fixed-position coords for a popover anchored to a trigger. Pure. Opens below the trigger when the
 * preferred height fits there (or below has more room), else above; the panel's edge follows the trigger's `align`
 * side, clamped into the viewport.
 */

export interface PopoverCoords {
  top?: number;
  bottom?: number;
  right?: number;
  left?: number;
  maxHeight: number;
}

/** `r` is the trigger's getBoundingClientRect(); `panel` the panel's width and preferred height. */
export function anchorPanel(
  r: Pick<DOMRect, "top" | "bottom" | "left" | "right">,
  panel: { width: number; height: number },
  viewport: { width: number; height: number },
  align: "left" | "right" = "left",
  margin = 8,
): PopoverCoords {
  const spaceAbove = r.top - margin;
  const spaceBelow = viewport.height - r.bottom - margin;
  const openDown = spaceBelow >= panel.height || spaceBelow > spaceAbove;
  const vert: { top?: number; bottom?: number; maxHeight: number } = openDown
    ? { top: r.bottom + margin, maxHeight: Math.min(panel.height, spaceBelow) }
    : { bottom: viewport.height - r.top + margin, maxHeight: Math.min(panel.height, spaceAbove) };
  if (align === "right") {
    const wantRight = viewport.width - r.right;
    const maxRight = viewport.width - panel.width - margin;
    return { ...vert, right: Math.max(margin, Math.min(wantRight, maxRight)) };
  }
  const wantLeft = r.left;
  const maxLeft = viewport.width - panel.width - margin;
  return { ...vert, left: Math.max(margin, Math.min(wantLeft, maxLeft)) };
}
