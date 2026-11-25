"use client";


import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import type { VaultMedia } from "@/lib/relay";
import { proxyImage, vaultTileThumb } from "@/lib/mediaUrl";
import { HOVER_DELAY_MS } from "@/hooks/useHoverPreview";

export const KEYBOARD_HINT = "Shift-click for a range · arrows to move";

type WithId = { id: number };

export function rangeBetween<T extends WithId>(items: T[], anchorId: number | null, targetId: number): T[] {
  const a = items.findIndex((m) => m.id === anchorId);
  const b = items.findIndex((m) => m.id === targetId);
  if (anchorId == null || a < 0 || b < 0) return [];
  return items.slice(Math.min(a, b), Math.max(a, b) + 1);
}

export function moveIndex(idx: number | null, key: string, cols: number, len: number): number | null {
  if (len === 0) return null;
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols }[key];
  if (step === undefined) return null;
  if (idx == null) return 0;
  return Math.max(0, Math.min(len - 1, idx + step));
}

export function gridColumnCount(grid: HTMLElement | null): number {
  if (!grid) return 1;
  const tracks = window.getComputedStyle(grid).gridTemplateColumns?.trim();
  if (tracks && tracks !== "none") return tracks.split(/\s+/).length;
  const tiles = Array.from(grid.children) as HTMLElement[];
  if (tiles.length === 0) return 1;
  const top = tiles[0].offsetTop;
  return Math.max(1, tiles.filter((t) => t.offsetTop === top).length);
}

export function useGridSelection<T extends WithId>(opts: {
  items: T[];
  toggle: (m: T) => void;
  addMany: (ms: T[]) => void;
  attach: (focused: T | undefined) => void;
}) {
  const { items, toggle, addMany, attach } = opts;
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [anchorId, setAnchorId] = useState<number | null>(null);

  const focusTile = (m: T) =>
    gridRef.current?.querySelector<HTMLElement>(`[data-tile-id="${m.id}"]`)?.focus();

  const onTileClick = (m: T, e: MouseEvent) => {
    const range = e.shiftKey ? rangeBetween(items, anchorId, m.id) : [];
    if (range.length > 0) addMany(range);
    else {
      toggle(m);
      setAnchorId(m.id);
    }
  };

  const onGridKeyDown = (e: KeyboardEvent) => {
    const tileId = (e.target as HTMLElement).closest("[data-tile-id]")?.getAttribute("data-tile-id");
    const idx = tileId == null ? -1 : items.findIndex((m) => m.id === Number(tileId));
    const focused = idx >= 0 ? items[idx] : undefined;
    const from = items.some((m) => m.id === anchorId) ? anchorId : focused?.id ?? null;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
      e.preventDefault();
      addMany(items);
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const next = moveIndex(idx >= 0 ? idx : null, e.key, gridColumnCount(gridRef.current), items.length);
    if (next != null) {
      e.preventDefault();
      if (e.shiftKey && from != null) {
        addMany(rangeBetween(items, from, items[next].id));
        setAnchorId(from);
      }
      focusTile(items[next]);
    } else if (e.key === " " && focused) {
      e.preventDefault();
      if (e.shiftKey && from != null) addMany(rangeBetween(items, from, focused.id));
      else {
        toggle(focused);
        setAnchorId(focused.id);
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      attach(focused);
    }
  };

  const onGridKeyUp = (e: KeyboardEvent) => {
    if (e.key === " ") e.preventDefault();
  };

  return { gridRef, onTileClick, onGridKeyDown, onGridKeyUp };
}

export function photoPreviewSrc(m: VaultMedia, accountId: string | null): string {
  return proxyImage(m.files?.preview?.url || m.files?.full?.url, accountId) || vaultTileThumb(m, accountId);
}

const PANEL = 420;

export function usePhotoHover() {
  const [shown, setShown] = useState<{ media: VaultMedia; left: number; top: number } | null>(null);
  const timer = useRef<number | null>(null);
  const clear = () => {
    if (timer.current != null) window.clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => clear, []);
  const start = (media: VaultMedia, tile: HTMLElement) => {
    clear();
    timer.current = window.setTimeout(() => {
      timer.current = null;
      const r = tile.getBoundingClientRect();
      const fitsRight = r.right + 8 + PANEL <= window.innerWidth;
      setShown({
        media,
        left: Math.max(8, fitsRight ? r.right + 8 : r.left - 8 - PANEL),
        top: Math.max(8, Math.min(r.top, window.innerHeight - PANEL - 8)),
      });
    }, HOVER_DELAY_MS);
  };
  const close = useCallback(() => {
    clear();
    setShown(null);
  }, []);
  return { shown, start, close };
}

export function PhotoHoverPanel({
  media, left, top, accountId, blurCls,
}: { media: VaultMedia; left: number; top: number; accountId: string | null; blurCls: string }) {
  const thumb = vaultTileThumb(media, accountId);
  return (
    <div
      aria-hidden
      className="fixed z-[70] pointer-events-none rounded-md overflow-hidden border border-border bg-black shadow-2xl"
      style={{ left, top, width: PANEL, height: PANEL }}
    >
      <img
        src={photoPreviewSrc(media, accountId)}
        alt="Photo preview"
        decoding="async"
        onError={(e) => {
          if (thumb && e.currentTarget.getAttribute("src") !== thumb) e.currentTarget.src = thumb;
        }}
        className={`w-full h-full object-contain ${blurCls}`}
      />
    </div>
  );
}
