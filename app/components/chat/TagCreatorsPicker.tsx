"use client";

/**
 * TagCreatorsPicker — popover for @-tagging other creators in a chat
 * message. Mirrors the desktop app's TagUserPicker: GETs OF's
 * /self/tagged-friend-users, searches by debounced query, multi-selects
 * via row click. Selected ids are owned by the parent (Composer) so the
 * chip row above the textarea can render them outside this popover.
 *
 * OnlyFans rejects userTags ids that aren't on the caller's tagged-friend
 * list with 400, so the picker IS the contract — never let users type
 * arbitrary ids.
 *
 * `messagesPro` (only the Composer passes it) is Infloww's "Tag other
 * Creators": a 34px @ toolbar icon (it took the place of "Mention this fan",
 * TODO.md A5), picks staged until "Add", and "More" ›
 * "Add a tag" › "Release form" Not wired (docs/spec/phase-04-composer-ppv-vault.md).
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { AtSign } from "lucide-react";

import { cn } from "@/lib/utils";
import { relay, toChoice, type TaggedCreatorChoice, type TaggedFriendUsersResp } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { useInflowwPalette } from "./InflowwPalette";
import { POP_HEAD, POP_PRIMARY, POP_ROW, TOOLBAR_ICON } from "./ComposerToolbar";

const PAGE = 20;
const DEBOUNCE_MS = 250;

export type { TaggedCreatorChoice };

export interface TagCreatorsPickerProps {
  accountId: string | null;
  selected: TaggedCreatorChoice[];
  onChange: (next: TaggedCreatorChoice[]) => void;
  disabled?: boolean;
  /** Messages Pro mode: picks apply only on "Add". */
  messagesPro?: boolean;
}

export function TagCreatorsPicker({
  accountId, selected, onChange, disabled, messagesPro,
}: TagCreatorsPickerProps) {
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
  const palette = useInflowwPalette();
  const [open, setOpen] = useState(false);
  // Messages Pro stages picks here, seeded from `selected` on open; closing
  // without "Add" drops them.
  const [staged, setStaged] = useState<TaggedCreatorChoice[]>([]);
  const [moreOpen, setMoreOpen] = useState(false);
  const picks = messagesPro ? staged : selected;
  const setPicks = messagesPro ? setStaged : onChange;
  const [rawSearch, setRawSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  // Portal+fixed coords so the popover escapes the host modal's overflow
  // clip (post/mass composers were chopping off the bottom and side of
  // the panel). Auto-picks up vs. down based on which side has room.
  const [coords, setCoords] = useState<{
    top?: number;
    bottom?: number;
    left: number;
    maxHeight: number;
  } | null>(null);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(rawSearch.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [rawSearch]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t)) return;
      if (popRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", onClick);
    return () => document.removeEventListener("pointerdown", onClick);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const r = buttonRef.current?.getBoundingClientRect();
      if (!r) return;
      const PANEL_W = 320;
      const PANEL_H_PREF = 384;
      const margin = 8;
      const wantLeft = r.left;
      const maxLeft = window.innerWidth - PANEL_W - margin;
      const left = Math.max(margin, Math.min(wantLeft, maxLeft));
      const spaceAbove = r.top - margin;
      const spaceBelow = window.innerHeight - r.bottom - margin;
      const openDown = spaceBelow >= PANEL_H_PREF || spaceBelow > spaceAbove;
      setCoords(openDown
        ? { top: r.bottom + 8, left, maxHeight: Math.min(PANEL_H_PREF, spaceBelow) }
        : { bottom: window.innerHeight - r.top + 8, left, maxHeight: Math.min(PANEL_H_PREF, spaceAbove) });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  const q = useQuery<TaggedFriendUsersResp>({
    queryKey: ["tagged-friend-users", accountId, debounced],
    enabled: open && !!accountId,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE));
      params.set("offset", "0");
      if (debounced) params.set("search", debounced);
      return relay.get<TaggedFriendUsersResp>(
        `/api/of/v2/posts/tagged-friend-users?${params.toString()}`,
        { accountId: accountId ?? undefined },
      );
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const selectedIds = useMemo(() => new Set(picks.map((c) => c.id)), [picks]);
  const rows: TaggedCreatorChoice[] = (q.data?.items ?? []).map(toChoice);

  function toggle(c: TaggedCreatorChoice) {
    if (selectedIds.has(c.id)) {
      setPicks(picks.filter((x) => x.id !== c.id));
    } else {
      setPicks([...picks, c]);
    }
  }

  function toggleOpen() {
    if (!open) {
      setStaged(selected);
      setMoreOpen(false);
    }
    setOpen(!open);
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        disabled={disabled || !accountId}
        aria-label={messagesPro ? "Tag other Creators" : undefined}
        title={messagesPro ? "Tag other Creators" : "Tag other creators in this message"}
        className={messagesPro ? cn(
          TOOLBAR_ICON,
          open || selected.length > 0 ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg",
        ) : cn(
          "w-8 h-8 grid place-items-center rounded-md border text-sm font-semibold",
          open || selected.length > 0
            ? "bg-accent/15 text-[var(--inf-accent-text,var(--color-accent))] border-accent/40"
            : "bg-transparent text-fg-dim border-border hover:bg-bg-elev-1",
          (disabled || !accountId) && "opacity-40 cursor-not-allowed",
        )}
      >
        {messagesPro ? <AtSign size={20} aria-hidden /> : <>
          @{selected.length > 0 && (
            <span className="ml-0.5 text-[10px] tabular-nums">{selected.length}</span>
          )}
        </>}
      </button>
      {open && coords && typeof document !== "undefined" && createPortal(
        <div
          ref={popRef}
          style={{
            ...palette,
            position: "fixed",
            top: coords.top,
            bottom: coords.bottom,
            left: coords.left,
            maxHeight: coords.maxHeight,
          }}
          role={messagesPro ? "region" : undefined}
          aria-label={messagesPro ? "Tag other Creators" : undefined}
          className="w-80 overflow-hidden flex flex-col bg-panel border border-border rounded-lg shadow-xl z-[60]"
        >
          {messagesPro && <div className={POP_HEAD}>Tag other Creators</div>}
          <div className="px-3 py-2 border-b border-border">
            <input
              ref={inputRef}
              type="text"
              value={rawSearch}
              onChange={(e) => setRawSearch(e.target.value)}
              placeholder="Search creators to tag…"
              className="w-full bg-bg border border-border rounded-md px-2 py-1 text-base md:text-sm focus:outline-none focus:border-accent"
            />
            <div className="mt-1 text-[10px] text-fg-dim">
              {q.isFetching ? "Searching…" : `${rows.length} result${rows.length === 1 ? "" : "s"}`}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {q.error && (
              <div className="px-3 py-2 text-xs text-err">
                {(q.error as Error).message || "Failed to load"}
              </div>
            )}
            {!q.isFetching && rows.length === 0 && !q.error && (
              <div className="px-3 py-6 text-xs text-fg-dim text-center">
                {debounced
                  ? "No creators match your search."
                  : "No taggable creators. OF only allows tagging mutual creators you've added."}
              </div>
            )}
            {rows.map((c) => {
              const isSel = selectedIds.has(c.id);
              const avatar = proxyImage(c.avatar, accountId);
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => toggle(c)}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-1.5 border-b border-border/40 hover:bg-bg-elev-1 transition-colors text-left",
                    isSel && "bg-accent/10",
                  )}
                >
                  <div className="w-7 h-7 rounded-full bg-bg-elev-1 overflow-hidden grid place-items-center text-[10px] text-fg-dim shrink-0">
                    {avatar ? (
                      <img src={avatar} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <span>{(c.name[0] || "?").toUpperCase()}</span>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-fg truncate">{c.name}</div>
                    {c.username && (
                      <div className="text-[10px] text-fg-dim truncate">@{c.username}</div>
                    )}
                  </div>
                  <span
                    className={cn(
                      "w-4 h-4 rounded grid place-items-center text-[10px] font-bold border",
                      isSel
                        ? "bg-accent border-accent text-[var(--inf-on-accent,var(--color-bg))]"
                        : "border-border text-transparent",
                    )}
                    aria-hidden
                  >
                    ✓
                  </span>
                </button>
              );
            })}
          </div>
          {picks.length > 0 && (
            <div className="px-3 py-1.5 border-t border-border bg-bg/60 flex items-center justify-between text-[11px]">
              <span className="text-fg-dim">{picks.length} selected</span>
              <button
                type="button"
                onClick={() => setPicks([])}
                className="px-3 py-3 -my-1.5 -mr-3 md:px-0 md:py-0 md:my-0 md:mr-0 text-fg-dim hover:text-fg underline underline-offset-2"
              >
                Clear all
              </button>
            </div>
          )}
          {messagesPro && (
            <div className="border-t border-border">
              {/* Not wired: the relay lists no release forms (spec, ASSUMPTION). */}
              {moreOpen && (
                <div role="group" aria-label="Add a tag">
                  <div className={POP_HEAD}>Add a tag</div>
                  <button
                    type="button"
                    disabled
                    title="not wired"
                    className={cn(POP_ROW, "w-full text-[13px] disabled:opacity-40 disabled:cursor-not-allowed")}
                  >
                    Release form
                  </button>
                </div>
              )}
              <div className="px-3 py-2 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setMoreOpen((v) => !v)}
                  aria-expanded={moreOpen}
                  className="text-[12.5px] text-fg-dim hover:text-fg"
                >
                  More
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onChange(staged);
                    setOpen(false);
                  }}
                  className={cn(POP_PRIMARY, "disabled:bg-[var(--inf-idle-fill,var(--color-bg-elev-2))]")}
                >
                  Add
                </button>
              </div>
            </div>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}

/** Chip row used by the Composer above the textarea so users see who's
 *  tagged without opening the popover. Click ✕ to drop one. */
export function TaggedCreatorChips({
  selected, onChange,
}: { selected: TaggedCreatorChoice[]; onChange: (next: TaggedCreatorChoice[]) => void }) {
  if (selected.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap bg-bg/60 border border-border rounded-lg px-2 py-1.5">
      <span className="text-[10px] uppercase tracking-wide text-fg-dim mr-1">Tagged</span>
      {selected.map((c) => (
        <span
          key={c.id}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent/15 text-[var(--inf-accent-text,var(--color-accent))] border border-accent/30 text-[11px]"
          title={c.username ? `@${c.username}` : c.name}
        >
          <span className="truncate max-w-[10rem]">{c.name}</span>
          <button
            type="button"
            onClick={() => onChange(selected.filter((x) => x.id !== c.id))}
            className="text-[var(--inf-accent-text,var(--color-accent))]/70 hover:text-[var(--inf-accent-text,var(--color-accent))]"
            aria-label={`Remove ${c.name}`}
          >
            ✕
          </button>
        </span>
      ))}
    </div>
  );
}
