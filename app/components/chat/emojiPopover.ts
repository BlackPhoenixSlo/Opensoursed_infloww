/**
 * Emoji picker popover placement — `anchorPanel` with the emoji panel's size
 * (384 wide, 400 preferred tall).
 */

import { anchorPanel, type PopoverCoords } from "@/lib/anchorPanel";

export type { PopoverCoords };

/** `r` is the trigger's getBoundingClientRect(). */
export function placeEmojiPopover(
  r: Pick<DOMRect, "top" | "bottom" | "left" | "right">,
  viewport: { width: number; height: number },
  align: "left" | "right",
): PopoverCoords {
  return anchorPanel(r, { width: 384, height: 400 }, viewport, align);
}
