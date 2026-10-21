"use client";

/**
 * MenuParts — the pieces every Chat header menu shares (spec M1): the menu
 * box and row, the Not wired row, and the status line each menu reports an
 * outcome on, with its `flash`. Used by the Kebab menu (`ChatActionsMenu`),
 * the Avatar menu (`AvatarMenu`) and the Extras overflow
 * (`ChatHeaderExtras`). The box and row are every Messages
 * Pro `.pop`'s, so the Fan List's and the Window header's menus use them too.
 * `ICON_BUTTON` (the Chat header's 30px icon button) lives here as well, since the
 * header modules that open these menus all read it.
 */

import { useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";

/** A `.pop` menu's box (`MP.menu.panel`, mh:361-363): it scrolls past its
 *  72vh, with the Clone's drop shadow, in our colours. Each menu adds its
 *  place (`MP.ours.<Component>`). */
export const MENU_PANEL = cn(MP.menu.panel, "overflow-auto overscroll-contain shadow-2xl bg-panel border-border");

/** A `.pop .prow` row (`MP.menu.row`, mh:364): one full-width line, its
 *  contents centred on it and left-aligned. Each menu adds its colours. */
export const MENU_ROW = cn(MP.menu.row, "flex w-full items-center text-left");

/** A `.pop` menu's box with no place of its own: it paints its own
 *  background, so it sets its own text colour too. The Kebab menu and its
 *  "Inflowwww extras ▸" submenu, which share one placed wrapper. */
export const MENU_BOX = cn(MENU_PANEL, "text-fg");

/** A `.pop` menu opening down from its trigger, every Chat header and Fan
 *  List menu. Each menu adds its place (`MP.ours.<Component>`). */
export const MENU = cn(MENU_BOX, "absolute top-full");

/** A menu row in our text and hover colours. */
export const MENU_ITEM = cn(MENU_ROW, "text-fg hover:bg-bg-elev-1");

/** A Chat header icon button (`.th-tools .icon-btn`, CH10; #tbModel): its
 *  icon centred. Each adds its colours. */
export const ICON_BUTTON = cn(MP.chatHeader.iconButton, "grid place-items-center");

/** A Not wired menu row (spec, "Not wired rendering"): `aria-disabled`, the
 *  title "not wired" and no click handler, so the tooltip still shows. */
export function NotWiredMenuRow({ children }: { children: ReactNode }) {
  return (
    <button
      type="button"
      aria-disabled="true"
      title="not wired"
      className={cn(MENU_ROW, "text-fg-dim cursor-not-allowed")}
    >
      {children}
    </button>
  );
}

export type MenuStatus = { ok: boolean; msg: string } | null;

/** A menu's status, and `flash`, which shows an outcome for 2.5 seconds. */
export function useMenuStatus() {
  const [status, setStatus] = useState<MenuStatus>(null);
  function flash(ok: boolean, msg: string) {
    setStatus({ ok, msg });
    setTimeout(() => setStatus(null), 2500);
  }
  return { status, flash };
}

/** The status line at the foot of a menu: ✓ and the success text, or ✗ and
 *  the error. Renders nothing while there is no status. */
export function MenuStatusLine({ status }: { status: MenuStatus }) {
  if (!status) return null;
  return (
    <div className={cn(MP.ours.MenuStatusLine.root, "border-border", status.ok ? "text-ok" : "text-err")}>
      {status.ok ? "✓ " : "✗ "}{status.msg}
    </div>
  );
}
