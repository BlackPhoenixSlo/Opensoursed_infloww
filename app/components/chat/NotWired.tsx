"use client";


import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export const NOT_WIRED = {
  priority: "Starring a fan needs a route to OnlyFans we don't have, so for now every fan is a priority. The Priority chip in the list shows who OnlyFans already starred.",
  pin: "Pinning a chat needs a route to OnlyFans we don't have, so your favourite scrolls like everyone else. The Pinned chip lists the chats OnlyFans already pinned.",
  rowClose: "Infloww draws this × on every row. Nobody has found out what it does, including us.",
  report: "OnlyFans' report form wants a captcha the relay cannot solve. Block works, and is quieter.",
  onlineStats: "No page counts online-fan blasts on their own yet. Mass message statistics, one row up, is real.",
  releaseForm: "OnlyFans lists no release forms to the relay. Get it signed the old-fashioned way.",
  vaultUnsend: "This history has no message id to unsend. Unsend it from the bubble in the chat instead.",
} as const;

export type NotWiredKey = keyof typeof NOT_WIRED;

export function notWiredTitle(key: NotWiredKey): string {
  return `not wired: ${NOT_WIRED[key]}`;
}

export const NOTE_MS = 4000;

export function useNotWiredNote() {
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const onClick = (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (timer.current) clearTimeout(timer.current);
    setOpen(true);
    timer.current = setTimeout(() => setOpen(false), NOTE_MS);
  };
  return { open, onClick };
}

export function NotWiredNote({ open, children, className }: { open: boolean; children: ReactNode; className?: string }) {
  if (!open) return null;
  return (
    <span
      role="status"
      className={cn(
        "absolute z-50 w-60 rounded-md border border-border bg-panel px-2.5 py-1.5 text-left text-xs font-normal leading-snug whitespace-normal text-fg shadow-xl",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function NotWiredButton({ why, label, className, notePlace = "top-full left-0 mt-1", children }: {
  why: NotWiredKey;
  label?: string;
  className?: string;
  notePlace?: string;
  children: ReactNode;
}) {
  const note = useNotWiredNote();
  return (
    <span className="relative inline-flex flex-none">
      <button
        type="button"
        aria-label={label}
        aria-disabled="true"
        title={notWiredTitle(why)}
        onClick={note.onClick}
        className={cn(className, "cursor-help")}
      >
        {children}
      </button>
      <NotWiredNote open={note.open} className={notePlace}>{NOT_WIRED[why]}</NotWiredNote>
    </span>
  );
}
