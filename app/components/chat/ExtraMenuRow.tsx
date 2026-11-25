import type { ReactNode } from "react";

import { extraTitle, type ExtraName } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { MENU_ITEM, MENU_ROW } from "./MenuParts";

export const CHAT_EXTRA_ROW = cn(MENU_ROW, "disabled:opacity-50");

export function ExtraMenuRow({
  name, onClick, children, className, disabled, pressed, expanded, detail,
}: {
  name: ExtraName;
  onClick: () => void; children: ReactNode;
  className?: string;
  disabled?: boolean;
  pressed?: boolean;
  expanded?: boolean;
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
