"use client";


import { useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { NOT_WIRED, notWiredTitle, useNotWiredNote, type NotWiredKey } from "./NotWired";

export const MENU_PANEL = cn(MP.menu.panel, "pop-menu origin-top overflow-auto overscroll-contain shadow-2xl bg-panel border-border");

export const MENU_ROW = cn(MP.menu.row, "flex w-full items-center text-left");

export const MENU_BOX = cn(MENU_PANEL, "text-fg");

export const MENU = cn(MENU_BOX, "absolute top-full");

export const MENU_ITEM = cn(MENU_ROW, "text-fg hover:bg-bg-elev-1");

export const ICON_BUTTON = cn(MP.chatHeader.iconButton, "grid place-items-center");

export function NotWiredMenuRow({ why, children }: { why: NotWiredKey; children: ReactNode }) {
  const note = useNotWiredNote();
  return (
    <>
      <button
        type="button"
        aria-disabled="true"
        title={notWiredTitle(why)}
        onClick={note.onClick}
        className={cn(MENU_ROW, "text-fg-dim cursor-help")}
      >
        {children}
      </button>
      {note.open && (
        <div role="status" className="px-3 pb-2 text-xs leading-snug text-fg-dim">{NOT_WIRED[why]}</div>
      )}
    </>
  );
}

export type MenuStatus = { ok: boolean; msg: string } | null;

export function useMenuStatus() {
  const [status, setStatus] = useState<MenuStatus>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function flash(ok: boolean, msg: string) {
    if (timer.current) clearTimeout(timer.current);
    setStatus({ ok, msg });
    timer.current = setTimeout(() => setStatus(null), 2500);
  }
  return { status, flash };
}

export function MenuStatusLine({ status }: { status: MenuStatus }) {
  if (!status) return null;
  return (
    <div className={cn(MP.ours.MenuStatusLine.root, "border-border", status.ok ? "text-ok" : "text-err")}>
      {status.ok ? "✓ " : "✗ "}{status.msg}
    </div>
  );
}
