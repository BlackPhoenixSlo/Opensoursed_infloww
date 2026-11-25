"use client";


import { useEffect, useEffectEvent, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MessageCircle } from "lucide-react";

import { useRenderCap } from "@/hooks/useRenderCap";
import { useSavedReplies } from "@/hooks/useSavedReplies";
import { useTemplates } from "@/hooks/useTemplates";
import { SCRIPT_SOURCE } from "@/lib/chatSlots";
import { isImeComposing } from "@/lib/ime";
import { anchorPanel, type PopoverCoords } from "@/lib/anchorPanel";
import { cn } from "@/lib/utils";
import type { OFMessageTemplate, SavedReply, VaultMedia } from "@/lib/relay";
import { useInflowwPalette } from "./InflowwPalette";
import { PILL, PILL_ICON, PILL_LABEL } from "./ComposerToolbar";
import { fmtPrice } from "@/lib/format";
import { hasHtml, isOfHtml, ofPlainText, ofText } from "@/lib/ofRichText";
import { OfRichText } from "./OfRichText";

export interface PickedTemplate {
  source: "of" | "local";
  text: string;
  displayText: string;
  mediaCount: number;
  price: number;
  lockedText: boolean;
  isWelcome: boolean;
  media: VaultMedia[];
  title?: string;
  previews: number[];
  taggedUsers: number[];
  gifId?: string | null;
  gifUrl?: string | null;
  scriptId?: string | null;
  scriptStep?: number | null;
  replyId?: number;
  removedMediaIds?: number[];
}

function fromOF(t: OFMessageTemplate): PickedTemplate {
  return {
    source: "of",
    text: ofPlainText(t.displayText || t.text),
    displayText: t.displayText || t.text,
    mediaCount: t.mediaCount ?? (t.media?.length ?? 0),
    price: t.price ?? 0,
    lockedText: !!t.lockedText,
    isWelcome: t.template === "reply_on_subscribe",
    media: (t.media ?? []).map((m) => ({
      id: m.id,
      type: (m.type as VaultMedia["type"]) || "photo",
      files: m.files ?? null,
    })),
    previews: [],
    taggedUsers: [],
  };
}

export function fromLocal(r: SavedReply): PickedTemplate {
  return {
    source: "local",
    text: hasHtml(r.text) ? ofPlainText(r.text) : r.text,
    displayText: isOfHtml(r.text) ? r.text : ofText(r.text),
    mediaCount: r.media?.length ?? 0,
    price: r.price ?? 0,
    lockedText: !!r.locked_text,
    isWelcome: false,
    title: r.title ?? undefined,
    media: (r.media ?? []).map((m) => ({
      id: m.id,
      type: (m.type as VaultMedia["type"]) || "photo",
      files: m.files ?? null,
    })),
    previews: r.previews ?? [],
    taggedUsers: r.tagged_users ?? [],
    gifId: r.gif_id ?? null,
    gifUrl: r.gif_url ?? null,
    scriptId: r.script_id ?? null,
    scriptStep: r.script_step ?? null,
    replyId: r.id,
    removedMediaIds: r.removed_media_ids ?? [],
  };
}

export interface TemplatePickerProps {
  accountId: string | null;
  onPick: (t: PickedTemplate) => void;
  hideImageTemplates?: boolean;
  messagesPro?: boolean;
  slashQuery?: string | null;
  onSlashClose?: () => void;
  activeScriptId?: string | null;
  pinnedScriptId?: string | null;
}

const haystacks = new WeakMap<PickedTemplate, string>();
function haystackOf(t: PickedTemplate): string {
  let h = haystacks.get(t);
  if (h === undefined) {
    h = [t.title, t.text, t.scriptId].map((v) => (v ?? "").toLowerCase()).join("\n");
    haystacks.set(t, h);
  }
  return h;
}

function templateHasNoImageMedia(t: PickedTemplate): boolean {
  if (!t.media || t.media.length === 0) return true;
  return !t.media.some((m) => {
    const tp = (m.type || "").toLowerCase();
    return tp !== "gif";
  });
}

export function TemplatePicker({
  accountId, onPick, hideImageTemplates, messagesPro, slashQuery = null, onSlashClose,
  activeScriptId = null, pinnedScriptId = null,
}: TemplatePickerProps) {
  const palette = useInflowwPalette();
  const [pillOpen, setPillOpen] = useState(false);
  const [typedSearch, setTypedSearch] = useState("");
  const slash = slashQuery !== null;
  const open = pillOpen || slash;
  const search = slash ? slashQuery : typedSearch;
  const close = () => {
    setPillOpen(false);
    if (slash) onSlashClose?.();
  };
  const pick = (t: PickedTemplate) => {
    onPick(t);
    close();
  };
  const anchorRef = useRef<Element | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [coords, setCoords] = useState<PopoverCoords | null>(null);
  const tplQ = useTemplates(open ? accountId : null);
  const replyQ = useSavedReplies(open ? accountId : null);
  const refetchReplies = replyQ.refetch;
  // Re-read on every open: a cached list can be a restored snapshot predating a script just saved.
  useEffect(() => {
    if (open && accountId) void refetchReplies({ cancelRefetch: false });
  }, [open, accountId, refetchReplies]);

  useEffect(() => {
    if (!open) {
      setTypedSearch("");
      return;
    }
    if (slash) return;
    const t = setTimeout(() => searchRef.current?.focus(), 30);
    return () => clearTimeout(t);
  }, [open, slash]);

  useEffect(() => {
    anchorRef.current = slash ? document.activeElement : null;
  }, [slash]);

  const onOutsidePress = useEffectEvent((e: PointerEvent) => {
    const t = e.target as Node;
    if (rootRef.current?.contains(t)) return;
    if (popRef.current?.contains(t)) return;
    if (slash && t === anchorRef.current) return;
    close();
  });
  useEffect(() => {
    if (!open) return;
    const onPress = (e: PointerEvent) => onOutsidePress(e);
    document.addEventListener("pointerdown", onPress);
    return () => document.removeEventListener("pointerdown", onPress);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const r = buttonRef.current?.getBoundingClientRect();
      if (!r) return;
      setCoords(anchorPanel(r, { width: 320, height: 384 }, { width: window.innerWidth, height: window.innerHeight }));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  const { allItems, visibleByImageFilter } = useMemo(() => {
    const welcome = (tplQ.data ?? []).find((t) => t.template === "reply_on_subscribe");
    const all = [...(welcome ? [fromOF(welcome)] : []), ...(replyQ.data ?? []).map(fromLocal)];
    return { allItems: all, visibleByImageFilter: hideImageTemplates ? all.filter(templateHasNoImageMedia) : all };
  }, [tplQ.data, replyQ.data, hideImageTemplates]);
  const hiddenCount = hideImageTemplates ? allItems.length - visibleByImageFilter.length : 0;
  const q = search.trim().toLowerCase();
  // Memoized: a library runs to 10k scripts.
  const pool = useMemo(() => {
    const lead = [...new Set([pinnedScriptId, activeScriptId])].filter((id): id is string => !!id);
    const source = SCRIPT_SOURCE;
    const shown = !source || q.startsWith(source.searchPrefix) ? visibleByImageFilter
      : visibleByImageFilter.filter((t) => !source.owns(t.scriptId) || t.scriptId === pinnedScriptId);
    if (lead.length === 0) return shown;
    const rank = (t: PickedTemplate) => {
      const i = lead.indexOf(t.scriptId ?? "");
      return i < 0 ? lead.length : i;
    };
    return [...shown].sort((a, b) => rank(a) - rank(b)
      || (rank(a) < lead.length ? (a.scriptStep ?? 0) - (b.scriptStep ?? 0) : 0));
  }, [visibleByImageFilter, q, pinnedScriptId, activeScriptId]);

  const items = useMemo(() => {
    if (!q) return pool;
    return pool.filter((t) => haystackOf(t).includes(q));
  }, [q, pool]);
  const { cap, hasMore, more, sentinel } = useRenderCap(items.length, `${open}|${q}`);

  // Escape stops at document so it never reaches the window Escape of Find or Fan insights.
  const onSlashKey = useEffectEvent((e: KeyboardEvent) => {
    if (isImeComposing(e) || e.target !== anchorRef.current) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
    if (e.key === "Enter" && !e.shiftKey && items[0]) pick(items[0]);
  });
  useEffect(() => {
    if (!slash) return;
    const onKey = (e: KeyboardEvent) => onSlashKey(e);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [slash]);

  const loading = tplQ.isFetching || replyQ.isFetching;
  const err = tplQ.error || replyQ.error;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => (open ? close() : setPillOpen(true))}
        disabled={!accountId}
        title="Insert saved template"
        className={messagesPro ? cn(PILL, "bg-[var(--inf-scripts-pill,var(--color-bg-elev-2))] text-[var(--inf-accent-text,var(--color-accent))]") : cn(
          "w-8 h-8 grid place-items-center rounded-md border text-sm",
          open
            ? "bg-accent/15 text-[var(--inf-accent-text,var(--color-accent))] border-accent/40"
            : "bg-transparent text-fg-dim border-border hover:bg-bg-elev-1",
          !accountId && "opacity-40 cursor-not-allowed",
        )}
      >
        {messagesPro ? <><MessageCircle {...PILL_ICON} /><span className={PILL_LABEL}>Scripts</span></> : "⌘"}
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
          className="w-80 flex flex-col overflow-hidden bg-panel border border-border rounded-lg shadow-xl z-[100]"
        >
          <div className="px-3 py-2 border-b border-border space-y-1.5">
            <input
              ref={searchRef}
              type="text"
              value={search}
              readOnly={slash}
              onChange={(e) => setTypedSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  if (search && !slash) {
                    e.preventDefault();
                    setTypedSearch("");
                  } else {
                    close();
                  }
                }
                if (e.key === "Enter" && items.length > 0 && !isImeComposing(e)) {
                  e.preventDefault();
                  pick(items[0]);
                }
              }}
              placeholder="Search templates…"
              className="w-full bg-bg border border-border rounded-md px-2 py-1 text-base md:text-sm focus:outline-none focus:border-accent"
            />
            <div className="text-[10px] text-fg-dim">
              {loading
                ? "Loading…"
                : `${items.length} of ${pool.length}`}
              {search && items.length > 0 && " · Enter to pick first"}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {err && (
              <div className="px-3 py-2 text-xs text-err">
                {(err as Error).message || "failed"}
              </div>
            )}
            {!loading && items.length === 0 && (
              <div className="px-3 py-4 text-xs text-fg-dim text-center">
                {search
                  ? `No templates match "${search}".`
                  : hiddenCount > 0
                    ? `No text/GIF-only templates. ${hiddenCount} hidden because they contain images.`
                    : "No templates yet. Create one in Settings → Templates."}
              </div>
            )}
            {hiddenCount > 0 && items.length > 0 && !search && (
              <div className="px-3 py-1.5 text-[10px] text-fg-dim border-b border-border/40 bg-bg/40">
                {hiddenCount} template{hiddenCount === 1 ? "" : "s"} hidden — contain images, not supported here.
              </div>
            )}
            {SCRIPT_SOURCE && pinnedScriptId && items[0]?.scriptId === pinnedScriptId && (
              <div className="px-3 py-1 text-[10px] text-[var(--inf-accent-text,var(--color-accent))] border-b border-border/40 bg-accent/5">
                {pinnedScriptId} · {SCRIPT_SOURCE.label}
              </div>
            )}
            {items.slice(0, cap).map((t, i) => (
              <button
                key={`${t.source}:${t.title ?? i}:${i}`}
                type="button"
                onClick={() => pick(t)}
                className="w-full text-left px-3 py-2 border-b border-border/40 hover:bg-bg-elev-1 transition-colors"
              >
                <div className="flex items-center flex-wrap md:flex-nowrap gap-x-2 gap-y-0.5 mb-0.5">
                  {t.isWelcome && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-[var(--inf-accent-text,var(--color-accent))]">👋 welcome</span>
                  )}
                  {t.source === "local" && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-bg-elev-1 text-fg-dim">local</span>
                  )}
                  {t.title && (
                    <span className="text-[10px] font-medium text-fg">{t.title}</span>
                  )}
                  {t.mediaCount > 0 && (
                    <span className="text-[10px] text-fg-dim">📎 {t.mediaCount}</span>
                  )}
                  {t.gifId && (
                    <span className="text-[10px] text-fg-dim" title="Includes a GIF">
                      🎬<span className="md:hidden"> gif</span>
                    </span>
                  )}
                  {t.scriptId && (
                    <span
                      className="text-[10px] px-1 rounded bg-accent/10 text-[var(--inf-accent-text,var(--color-accent))]"
                      title={`Part of script "${t.scriptId}" · step ${t.scriptStep ?? "?"}`}
                    >
                      ▶ {t.scriptId}{t.scriptStep != null ? `·${t.scriptStep}` : ""}
                    </span>
                  )}
                  {t.price > 0 && (
                    <span className="text-[10px] text-warn">🔒 {fmtPrice(Math.round(t.price * 100))}</span>
                  )}
                  {t.previews.length > 0 && (
                    <span className="text-[10px] text-fg-dim" title="Free previews on apply">
                      👁 {t.previews.length}<span className="md:hidden"> free</span>
                    </span>
                  )}
                  {t.taggedUsers.length > 0 && (
                    <span className="text-[10px] text-[var(--inf-accent-text,var(--color-accent))]" title="@-tags applied on pick">
                      @{t.taggedUsers.length}<span className="md:hidden"> tagged</span>
                    </span>
                  )}
                </div>
                <div className="text-sm md:text-xs text-fg line-clamp-2"><OfRichText raw={t.displayText} /></div>
              </button>
            ))}
            {hasMore && (
              <div ref={sentinel}>
                <button type="button" onClick={more} className="w-full py-2 text-xs text-fg-dim hover:text-fg">
                  Show more ({items.length - cap})
                </button>
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

export function templateMediaToVault(t: PickedTemplate): VaultMedia[] {
  return t.media;
}
