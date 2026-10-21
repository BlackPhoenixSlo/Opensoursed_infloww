/**
 * ExtraMenuRow — one row of an Extras overflow menu (ADR-0003): a Fan List
 * menu row carrying its extra's tooltip from the catalogue (`extraTitle`):
 * "Inflowwww extra — <name>", then `detail` on a second line. Shared by
 * the Fan List's "+" overflow, the Window header's and the Chat header's
 * (`ChatHeaderExtras`, which passes its own Geometry through `className`).
 */

import type { ReactNode } from "react";

import { extraTitle, type ExtraName } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { MENU_ITEM, MENU_ROW } from "./MenuParts";

/** A Chat header Extras overflow row's `className`: the shared menu row,
 *  dimmed when disabled. */
export const CHAT_EXTRA_ROW = cn(MENU_ROW, "disabled:opacity-50");

export function ExtraMenuRow({
  name, onClick, children, className, disabled, pressed, expanded, detail,
}: {
  /** The extra this row is, as the catalogue names it. */
  name: ExtraName;
  onClick: () => void; children: ReactNode;
  /** Merged over the menu row (`MENU_ITEM`; later classes win). */
  className?: string;
  disabled?: boolean;
  /** `aria-pressed`, for a toggle row. */
  pressed?: boolean;
  /** `aria-expanded`, for a row that opens content under it. */
  expanded?: boolean;
  /** The tooltip's second line: the control's old tooltip, or why the row
   *  cannot say more. */
  detail?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={pressed}
      aria-expanded={expanded}
      title={extraTitle(name, detail)}
      className={cn(MENU_ITEM, className)}
    >
      {children}
    </button>
  );
}
