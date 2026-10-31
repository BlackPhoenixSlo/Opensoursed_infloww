"use client";

/**
 * EmojiBar — quick-row + picker popover with search + recents.
 *
 * Insertion preserves the textarea's cursor so the user can type, drop
 * an emoji, keep typing. The full emoji set lives in emojiData.ts;
 * the picker shows them tabbed by category with a search box that
 * matches by keyword.
 *
 * Recents persist in localStorage so the picker remembers what you used
 * across reloads.
 */

import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Smile } from "lucide-react";

import { loadFavourites } from "@/lib/emojiFavourites";
import { cn } from "@/lib/utils";
import { CATEGORIES, EMOJI_LIST, QUICK_EMOJIS } from "./emojiData";
import { placeEmojiPopover, type PopoverCoords } from "./emojiPopover";
import { emojiPickerReducer, filterEmojis, initialPickerState, tabEmojis } from "./emojiPickerReducer";
import { buildQuickRow, loadRecents, pushRecent, subscribeRecents } from "./emojiRecents";
import { useInflowwPalette } from "./InflowwPalette";

export { EMOJI_LIST, QUICK_EMOJIS };

/** Insert text at the current cursor of a textarea + restore focus. */
export function insertAtCursor(
  textarea: HTMLTextAreaElement,
  current: string,
  inserted: string,
  setValue: (s: string) => void,
) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const next = current.slice(0, start) + inserted + current.slice(end);
  setValue(next);
  setTimeout(() => {
    textarea.focus();
    textarea.selectionStart = textarea.selectionEnd = start + inserted.length;
  }, 0);
}

/** One emoji-picker tab button (Favourites, Recent, each category). */
function tabClass(active: boolean) {
  return cn(
    "px-3 py-2 md:px-2 md:py-1 rounded-md text-xl md:text-base shrink-0",
    active ? "bg-bg-elev-1" : "hover:bg-bg-elev-1/50",
  );
}

export function EmojiQuickRow({
  onInsert, disabled, slots = 8,
}: { onInsert: (e: string) => void; disabled?: boolean; slots?: number }) {
  const [recents, setRecents] = useState<string[]>([]);

  // Initial hydrate + follow recents changes (same tab and cross-tab) so a
  // pick in the popover re-shuffles every visible row.
  useEffect(() => {
    setRecents(loadRecents());
    return subscribeRecents(() => setRecents(loadRecents()));
  }, []);

  const row = useMemo(() => buildQuickRow(recents, slots), [recents, slots]);

  /** One quick-row button; `size` is the only difference between the rows. */
  const quickBtn = (size: string) => (e: string) => (
    <button
      key={e}
      type="button"
      disabled={disabled}
      onClick={() => { pushRecent(e); onInsert(e); }}
      className={`${size} grid place-items-center rounded-md hover:bg-bg-elev-1 disabled:opacity-40 text-base`}
    >
      {e}
    </button>
  );

  return (
    <>
      {/* Desktop row — unchanged: all 8 slots, 28px buttons. `hidden md:flex`
       *  (no bare `flex`) so it computes to display:flex at >=768px exactly
       *  as the original single div did. */}
      <div className="hidden md:flex gap-1">{row.map(quickBtn("w-7 h-7"))}</div>
      {/* Phone row — 5 slots at 40px. display:none at >=768px, so it
       *  generates no box and cannot affect the desktop flex line. */}
      <div className="md:hidden flex gap-1">{row.slice(0, 5).map(quickBtn("w-10 h-10"))}</div>
    </>
  );
}

export function EmojiPickerButton({
  onInsert, disabled, align = "right", triggerClassName, messagesPro,
}: {
  onInsert: (e: string) => void;
  disabled?: boolean;
  align?: "left" | "right";
  /** Overrides the trigger's size and shape (the Messages Pro button row). */
  triggerClassName?: string;
  /** Messages Pro mode (only the Composer): a "Favourites" tab, first and
   *  selected on open whenever favourites exist. */
  messagesPro?: boolean;
}) {
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
  const palette = useInflowwPalette();
  const [state, dispatch] = useReducer(emojiPickerReducer, initialPickerState);
  const { open, tab, search, recents, favourites } = state;
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [coords, setCoords] = useState<PopoverCoords | null>(null);

  // Re-load recents whenever the picker opens so we pick up clicks from
  // other components (quick-row) that also write to the store. While open,
  // also follow recents changes so the recents tab stays live as picks
  // land elsewhere.
  useEffect(() => {
    if (!open) return;
    dispatch({ type: "opened", recents: loadRecents(), favourites: messagesPro ? loadFavourites() : [] });
    setTimeout(() => searchInputRef.current?.focus(), 50);
    return subscribeRecents(() => dispatch({ type: "recentsRefreshed", recents: loadRecents() }));
  }, [open, messagesPro]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (popoverRef.current?.contains(t)) return;
      if (popRef.current?.contains(t)) return;
      dispatch({ type: "closed" });
    };
    window.addEventListener("pointerdown", onClick);
    return () => window.removeEventListener("pointerdown", onClick);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const r = buttonRef.current?.getBoundingClientRect();
      if (!r) return;
      setCoords(placeEmojiPopover(r, { width: window.innerWidth, height: window.innerHeight }, align));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, align]);

  const filtered = useMemo(() => filterEmojis(search), [search]);

  function pick(e: string) {
    pushRecent(e);
    onInsert(e);
    dispatch({ type: "closed" });
  }

  const gridEmojis = tabEmojis(state);

  return (
    <div ref={popoverRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        onClick={() => dispatch({ type: "toggled" })}
        className={cn(
          "w-8 h-8 grid place-items-center rounded-md hover:bg-bg-elev-1 disabled:opacity-40",
          messagesPro && (open ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg"),
          triggerClassName,
        )}
        aria-label="Emoji picker"
      >
        {/* Messages Pro draws Infloww's outline smiley, its row's 20px glyph. */}
        {messagesPro ? <Smile size={20} strokeWidth={1.6} aria-hidden /> : "😊"}
      </button>
      {open && coords && typeof document !== "undefined" && createPortal(
        <div
          ref={popRef}
          style={{
            ...palette,
            position: "fixed",
            top: coords.top,
            bottom: coords.bottom,
            right: coords.right,
            left: coords.left,
            maxHeight: coords.maxHeight,
          }}
          className={cn(
            "z-[60] flex flex-col",
            "bg-panel border border-border rounded-xl shadow-lg",
            "w-96 max-w-[90vw]",
          )}
        >
          <div className="p-2 border-b border-border">
            <input
              ref={searchInputRef}
              type="text"
              value={search}
              onChange={(e) => dispatch({ type: "searchSet", search: e.target.value })}
              placeholder="Search emoji…"
              className="w-full bg-bg border border-border rounded-md px-2 py-1 text-base md:text-xs placeholder:text-muted focus:outline-none focus:border-accent"
            />
          </div>

          {search.trim() ? (
            <div className="p-2 flex-1 min-h-0 overflow-y-auto">
              {filtered.length === 0 ? (
                <div className="text-xs text-fg-dim text-center py-6">
                  No emoji match &ldquo;{search}&rdquo;.
                </div>
              ) : (
                <div className="grid grid-cols-6 md:grid-cols-8 gap-1">
                  {filtered.map((e) => (
                    <EmojiBtn key={e} emoji={e} onClick={pick} />
                  ))}
                </div>
              )}
            </div>
          ) : (
            <>
              <div className="flex items-center gap-1 px-2 pt-2 overflow-x-auto scrollbar-thin">
                {favourites.length > 0 && (
                  <button
                    type="button"
                    onClick={() => dispatch({ type: "tabSet", tab: "favourites" })}
                    aria-pressed={tab === "favourites"}
                    aria-label="Favourites"
                    className={tabClass(tab === "favourites")}
                    title="Favourites"
                  >
                    ⭐
                  </button>
                )}
                {recents.length > 0 && (
                  <button
                    type="button"
                    onClick={() => dispatch({ type: "tabSet", tab: "recents" })}
                    className={tabClass(tab === "recents")}
                    title="Recent"
                  >
                    🕘
                  </button>
                )}
                {CATEGORIES.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => dispatch({ type: "tabSet", tab: c.id })}
                    className={tabClass(tab === c.id)}
                    title={c.id}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
              <div className="p-2 flex-1 min-h-0 overflow-y-auto">
                <div className="grid grid-cols-6 md:grid-cols-8 gap-1">
                  {gridEmojis.map((e, i) => (
                    <EmojiBtn key={`${e}-${i}`} emoji={e} onClick={pick} />
                  ))}
                </div>
              </div>
            </>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}

function EmojiBtn({ emoji, onClick }: { emoji: string; onClick: (e: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onClick(emoji)}
      className="w-11 h-11 md:w-7 md:h-7 grid place-items-center rounded-md hover:bg-bg-elev-1 text-2xl md:text-base"
    >
      {emoji}
    </button>
  );
}
