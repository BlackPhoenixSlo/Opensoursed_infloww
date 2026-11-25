"use client";


import { useEffect, useMemo, useRef, useState } from "react";
import { Pin } from "lucide-react";

import { clockTime } from "@/lib/format";
import { MP } from "@/lib/messagesPro";
import { cn, decodeHtmlEntities } from "@/lib/utils";
import type { OFMessage } from "@/lib/relay";

const FALLBACK_TOP_PX = 386;

interface PinnedBarProps {
  pinned: OFMessage[];
  open: boolean;
  onToggle: () => void;
}

export function PinnedBar({ pinned, open, onToggle }: PinnedBarProps) {
  if (pinned.length === 0) return null;
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        MP.messageList.pinBar, "flex w-full items-center border-[var(--inf-rule,var(--color-border))]",
        "bg-[var(--inf-pane,var(--color-panel))]/60 hover:bg-bg-elev-1/60 transition-colors text-left",
        open && "bg-bg-elev-1/80",
      )}
      title={open ? "Close pinned messages" : "Show pinned messages"}
    >
      <Pin aria-hidden className={cn(MP.messageList.pinBarIcon, "flex-none text-pink")} />
      <span className={cn(MP.messageList.pinCount, "text-fg")}>
        {pinned.length} pinned message{pinned.length === 1 ? "" : "s"}
      </span>
      <span className="text-fg-dim">
        · click to {open ? "close" : "view"}
      </span>
    </button>
  );
}

interface PinnedPopoverProps {
  pinned: OFMessage[];
  ownerUserId: number | null;
  open: boolean;
  onClose: () => void;
  onJumpTo: (messageId: number) => void;
}

export function PinnedPopover({
  pinned, ownerUserId, open, onClose, onJumpTo,
}: PinnedPopoverProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [topPx, setTopPx] = useState<number>(FALLBACK_TOP_PX);

  const ordered = useMemo(() => {
    return [...pinned].sort((a, b) => {
      const ta = a.createdAt ? Date.parse(a.createdAt) || 0 : 0;
      const tb = b.createdAt ? Date.parse(b.createdAt) || 0 : 0;
      return tb - ta;
    });
  }, [pinned]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (ref.current?.contains(target)) return;
      const el = target as HTMLElement;
      // Composer clicks keep it open so the chatter can type against the pinned context.
      if (el.closest && el.closest("[data-composer-area]")) return;
      if (el.closest && el.closest("[data-chat-row]")) return;
      onClose();
    };
    const t = setTimeout(() => {
      document.addEventListener("pointerdown", onDocClick);
    }, 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("pointerdown", onDocClick);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const measure = () => {
      const rows = document.querySelectorAll<HTMLElement>("[data-chat-row]");
      const anchor = rows[2] ?? rows[rows.length - 1];
      if (!anchor) {
        setTopPx(FALLBACK_TOP_PX);
        return;
      }
      const rect = anchor.getBoundingClientRect();
      setTopPx(Math.round(rect.bottom));
    };
    measure();
    const t = setTimeout(measure, 80);
    window.addEventListener("resize", measure);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  if (!open || ordered.length === 0) return null;

  return (
    <div
      ref={ref}
      style={{ top: topPx }}
      className={cn(
        MP.panes.pinnedOverlay, MP.ours.PinnedPanel.overlay, "fixed z-30",
        "bg-panel border-border shadow-2xl",
        "flex flex-col overflow-hidden",
      )}
      role="dialog"
      aria-label="Pinned messages"
    >
      <div className={cn(MP.ours.PinnedPanel.head, "border-border flex items-center")}>
        <span aria-hidden>📌</span>
        <span className="font-medium">Pinned messages</span>
        <span className="text-fg-dim">· {ordered.length}</span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto text-fg-dim hover:text-fg leading-none"
          aria-label="Close"
          title="Close"
        >
          ✕
        </button>
      </div>
      <div className="overflow-y-auto flex-1">
        {ordered.map((m) => {
          const isOutgoing = ownerUserId != null && m.fromUser?.id === ownerUserId;
          const senderName = isOutgoing
            ? "You"
            : decodeHtmlEntities(m.fromUser?.name || m.fromUser?.username || "fan");
          const preview = stripPreview(m.text || "", 120);
          const mediaCount = m.media?.length ?? m.mediaCount ?? 0;
          return (
            <button
              key={String(m.id)}
              type="button"
              onClick={() => {
                onJumpTo(Number(m.id));
                onClose();
              }}
              className={cn(
                "w-full text-left px-3 py-2 border-b border-border/60 last:border-b-0",
                "hover:bg-bg-elev-1/40 transition-colors",
              )}
            >
              <div className={cn(MP.ours.PinnedPanel.who, "flex items-baseline")}>
                <span className={cn("font-medium", isOutgoing ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg")}>
                  {senderName}
                </span>
                <span className="text-fg-dim">{fmtTime(m.createdAt)}</span>
              </div>
              {preview && (
                <div className={cn(MP.ours.PinnedPanel.preview, "text-fg-dim break-words whitespace-pre-wrap line-clamp-3")}>
                  {preview}
                </div>
              )}
              {mediaCount > 0 && (
                <div className={cn(MP.ours.PinnedPanel.media, "text-fg-dim inline-flex items-center")}>
                  <span aria-hidden>📎</span>
                  <span>{mediaCount} media — click to view</span>
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function stripPreview(html: string, max: number): string {
  const plain = html.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
  if (plain.length <= max) return plain;
  return plain.slice(0, max - 1) + "…";
}

export function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const time = clockTime(d);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) return time;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}
