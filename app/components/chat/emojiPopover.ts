import { anchorPanel, type PopoverCoords } from "@/lib/anchorPanel";

export type { PopoverCoords };

export function placeEmojiPopover(
  r: Pick<DOMRect, "top" | "bottom" | "left" | "right">,
  viewport: { width: number; height: number },
  align: "left" | "right",
): PopoverCoords {
  return anchorPanel(r, { width: 384, height: 400 }, viewport, align);
}
