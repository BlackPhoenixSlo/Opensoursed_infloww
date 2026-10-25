"use client";

/**
 * NotWired — Messages Pro's dead controls, and what each says when touched.
 * The screen copies Infloww pixel for pixel, so it draws a few controls no
 * relay route stands behind (spec, "Not wired rendering"). They used to be
 * titled "not wired" and swallow the click, which reads as broken. Now each
 * says, on hover and on click, what it would do and why it does not, in the
 * site's own dry voice ("The software is real; the jokes are ours.").
 *
 * The title still starts "not wired" (`notWiredTitle`), so the house marker
 * stays greppable. A click shows the same excuse in a small note for a few
 * seconds (`useNotWiredNote`, `NotWiredNote`); nothing is called, stored or
 * selected.
 */

import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Every dead control on the chat screen, and its excuse. */
export const NOT_WIRED = {
  priority: "Starring a fan needs a route to OnlyFans we don't have, so for now every fan is a priority. The Priority chip in the list shows who OnlyFans already starred.",
  pin: "Pinning a chat needs a route to OnlyFans we don't have, so your favourite scrolls like everyone else. The Pinned chip lists the chats OnlyFans already pinned.",
  rowClose: "Infloww draws this × on every row. Nobody has found out what it does, including us.",
  aa: "OnlyFans strips formatting from DMs, so this would only be decoration. It is already decoration.",
  report: "OnlyFans' report form wants a captcha the relay cannot solve. Block works, and is quieter.",
  onlineStats: "No page counts online-fan blasts on their own yet. Mass message statistics, one row up, is real.",
  releaseForm: "OnlyFans lists no release forms to the relay. Get it signed the old-fashioned way.",
  vaultUnsend: "This history has no message id to unsend. Unsend it from the bubble in the chat instead.",
} as const;

export type NotWiredKey = keyof typeof NOT_WIRED;

/** The title a dead control carries: the house marker, then its excuse. */
export function notWiredTitle(key: NotWiredKey): string {
  return `not wired: ${NOT_WIRED[key]}`;
}

/** How long a click's note stays up. */
export const NOTE_MS = 4000;

/** A dead control's click: it shows the excuse for `NOTE_MS` and goes no
 *  further (no row selection, no menu dismissal by the click itself). */
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

/** The note a click shows: a small bubble placed by `className` against the
 *  nearest positioned box. `role="status"`, so a screen reader reads it. */
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

/** A dead icon button (Chat header star and pin, the Composer's "Aa"):
 *  `aria-disabled`, titled with its excuse, which a click shows in a note.
 *  `notePlace` puts the note (below the icon by default). */
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
