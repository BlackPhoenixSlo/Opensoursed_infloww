"use client";


import { useEffect, useId, useState } from "react";
import { Settings } from "lucide-react";

import {
  FAVOURITES_EVENT, MAX_FAVOURITES, hasSavedFavourites, loadFavourites, saveFavourites,
} from "@/lib/emojiFavourites";
import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { POP_HEAD, POP_PRIMARY, POP_ROW, POP_START, ROW_ICON, usePopover } from "./ComposerToolbar";
import { EMOJI_LIST, QUICK_EMOJIS } from "./EmojiBar";

const GRID = [...new Set(EMOJI_LIST)];

function loadQuickEmojis(): string[] {
  return hasSavedFavourites() ? loadFavourites() : [...QUICK_EMOJIS];
}

export function QuickEmojiRow({ onInsert, disabled }: { onInsert: (emoji: string) => void; disabled?: boolean }) {
  const [emojis, setEmojis] = useState<string[]>([...QUICK_EMOJIS]);
  useEffect(() => {
    const refresh = () => setEmojis(loadQuickEmojis());
    refresh();
    window.addEventListener(FAVOURITES_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(FAVOURITES_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);
  return (
    <div role="group" aria-label="Quick emojis" className="flex items-center min-w-0 overflow-x-auto">
      {emojis.map((e) => (
        <button
          key={e}
          type="button"
          onClick={() => onInsert(e)}
          disabled={disabled}
          title={`Insert ${e} (pick your quick emojis with the gear)`}
          className="w-7 h-7 shrink-0 grid place-items-center rounded-md text-base hover:bg-bg-elev-1 disabled:opacity-40"
        >
          {e}
        </button>
      ))}
    </div>
  );
}

export function EmojiFavouritesButton({ disabled }: { disabled?: boolean }) {
  const { open, setOpen, rootRef } = usePopover();
  const id = useId();
  const [draft, setDraft] = useState<string[]>([]);
  const full = draft.length >= MAX_FAVOURITES;

  function toggle(e: string) {
    setDraft((d) => (d.includes(e) ? d.filter((x) => x !== e) : [...d, e]));
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => {
          if (!open) setDraft(loadQuickEmojis());
          setOpen(!open);
        }}
        disabled={disabled}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label="Emoji favourites"
        title="Emoji favourites"
        className={cn(ROW_ICON, open ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg")}
      >
        <Settings aria-hidden className={MP.ours.EmojiFavourites.gearIcon} />
      </button>
      {open && (
        <section
          id={id}
          aria-label="Emoji favourites"
          className={cn(POP_START, "flex flex-col overflow-hidden")}
        >
          <div className={cn(POP_HEAD, "flex justify-between")}>
            <span>Emoji favourites</span>
            <span className="tabular-nums">{draft.length}/{MAX_FAVOURITES}</span>
          </div>
          <div
            role="group"
            aria-label="Emojis"
            className={cn(MP.ours.EmojiFavourites.grid, "grid grid-cols-8 min-h-0 overflow-y-auto")}
          >
            {GRID.map((e) => {
              const picked = draft.includes(e);
              return (
                <button
                  key={e}
                  type="button"
                  onClick={() => toggle(e)}
                  disabled={full && !picked}
                  aria-pressed={picked}
                  className={cn(
                    "w-7 h-7 grid place-items-center rounded-md text-base disabled:opacity-30",
                    picked ? "bg-accent/15 ring-1 ring-accent/35" : "hover:bg-bg-elev-1",
                  )}
                >
                  {e}
                </button>
              );
            })}
          </div>
          <div className={cn(POP_ROW, "justify-end")}>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className={cn(MP.ours.EmojiFavourites.cancel, "text-fg-dim hover:text-fg hover:bg-bg-elev-1")}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                saveFavourites(draft);
                setOpen(false);
              }}
              className={cn(POP_PRIMARY, "disabled:bg-[var(--inf-idle-fill,var(--color-bg-elev-2))]")}
            >
              Save
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
