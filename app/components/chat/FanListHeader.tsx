"use client";

/**
 * FanListHeader — the top of the Fan List: the title (the Creator's name, or
 * "All Models"), then Infloww's gallery, search and "+" in that order. The
 * gallery icon opens the open Fan's "Chat gallery" sheet, and with no Fan
 * open it is disabled and says why (the Clone's handler, m.js:3209-3212;
 * docs/spec/messages-pro-look-and-feel/phase-02-fan-list-rows-and-header.md,
 * Gallery). The search icon opens the search input row under it, and "+" the
 * New menu. FanList owns the query and passes it in with its callback
 * (docs/spec/phase-02-fan-list-pane.md, Interfaces and Header). The refresh
 * icon and the gear live in FanListFilters' filter row.
 */

import { useId, useRef, useState, type ComponentProps } from "react";
import { Image as ImageIcon, Plus, Search } from "lucide-react";
import { LazyMassMessageComposer } from "@/components/compose/LazyMassMessageComposer";
import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { ChatGallery } from "./ChatGallery";
import { MENU, MENU_ITEM } from "./MenuParts";
import { useFanListMenu } from "./useFanListMenu";

const G = MP.fanList;

/** The header's icon buttons (gallery, search, "+"): centred glyph, dim
 *  until hovered. Each adds its box leaf; the gallery adds its disabled look. */
const ICON_BUTTON = "grid place-items-center shrink-0 text-fg-dim hover:text-fg hover:bg-bg-elev-1";

type ComposerMode = NonNullable<ComponentProps<typeof LazyMassMessageComposer>["mode"]>;

/** A New menu row: it opens the mass-message composer in a mode, or goes to
 *  a page. */
type NewMenuItem = { label: string } & ({ composer: ComposerMode } | { href: string });

/** The New menu's rows, Infloww's three in its order (Gap row 5; spec,
 *  Header): the composer in its standard and online modes, as Growth >
 *  Smart Messages opens it, and OF Manager's New post page. */
const NEW_MENU_ITEMS: readonly NewMenuItem[] = [
  { label: "Mass message", composer: "standard" },
  { label: "Message online fans", composer: "online" },
  { label: "Post", href: "/of-manager/new-post" },
];

/** The "+" New button and its menu (Gap rows 4-5). A composer row hands its
 *  mode to `onCompose`. */
function NewMenu({ onCompose }: { onCompose: (mode: ComposerMode) => void }) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const row = (item: NewMenuItem) =>
    "href" in item ? (
      // A main-app page: a new tab, so Messages Pro stays its own window.
      <a key={item.label} href={item.href} target="_blank" rel="noopener" onClick={() => setOpen(false)} className={MENU_ITEM}>
        {item.label}
      </a>
    ) : (
      <button
        key={item.label}
        type="button"
        onClick={() => { setOpen(false); onCompose(item.composer); }}
        className={MENU_ITEM}
      >
        {item.label}
      </button>
    );
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        {...triggerProps}
        className={cn(G.iconButton, ICON_BUTTON)}
        aria-label="New"
      >
        <Plus className={G.iconButtonIcon} />
      </button>
      {open && (
        <section {...menuProps} aria-label="New" className={cn(MENU, MP.ours.FanListHeader.menuPlace)}>
          {NEW_MENU_ITEMS.map(row)}
        </section>
      )}
    </div>
  );
}

export function FanListHeader({
  title, creatorId, query, onQueryChange, galleryFan,
}: {
  title: string;
  /** The Creator in scope, or null in All Models. */
  creatorId: string | null;
  query: string;
  onQueryChange: (next: string) => void;
  /** The open Fan, whose Chat gallery the gallery icon opens; null disables it. */
  galleryFan: { accountId: string; fanId: FanId } | null;
}) {
  // The Fan the sheet was opened for, so it never shows another Fan's media.
  const [galleryFor, setGalleryFor] = useState<typeof galleryFan>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [composer, setComposer] = useState<ComposerMode | null>(null);
  const searchButtonRef = useRef<HTMLButtonElement | null>(null);
  const searchRowId = useId();
  // Closing the row drops the query, so no hidden search narrows the list.
  const closeSearch = () => {
    setSearchOpen(false);
    onQueryChange("");
    searchButtonRef.current?.focus();
  };
  return (
    <>
      <div role="group" aria-label="Fan List header" className={cn(G.head, "flex items-center border-[var(--inf-rule,var(--color-border))]")}>
        <h2 className={cn(G.title, "flex-1 min-w-0 truncate")}>{title}</h2>
        <button
          type="button"
          onClick={() => setGalleryFor(galleryFan)}
          disabled={galleryFan === null}
          aria-haspopup="dialog"
          title={galleryFan ? "Chat gallery" : "Open a conversation to browse its media"}
          className={cn(G.gallery, ICON_BUTTON, "disabled:opacity-50 disabled:cursor-not-allowed")}
          aria-label="Gallery"
        >
          <ImageIcon aria-hidden className={G.iconButtonIcon} />
        </button>
        <button
          ref={searchButtonRef}
          type="button"
          onClick={() => (searchOpen ? closeSearch() : setSearchOpen(true))}
          className={cn(G.iconButton, ICON_BUTTON)}
          aria-label="Search"
          aria-expanded={searchOpen}
          aria-controls={searchOpen ? searchRowId : undefined}
        >
          <Search className={G.iconButtonIcon} />
        </button>
        <NewMenu onCompose={setComposer} />
      </div>
      {searchOpen && (
        <div id={searchRowId} className="px-4 pb-3">
          <input
            type="text"
            autoFocus
            placeholder="Search…"
            value={query}
            onChange={(e) => (e.target.value === "" ? closeSearch() : onQueryChange(e.target.value))}
            onKeyDown={(e) => { if (e.key === "Escape") closeSearch(); }}
            className="w-full bg-bg border border-border rounded-md px-3 py-2.5 text-base md:px-2 md:py-1.5 md:text-xs placeholder:text-muted focus:outline-none focus:border-accent"
          />
        </div>
      )}
      {galleryFor && (
        <ChatGallery accountId={galleryFor.accountId} fanId={galleryFor.fanId} onClose={() => setGalleryFor(null)} />
      )}
      {/* In a single-Creator scope the composer opens with that Creator as
       *  its account; in All Models it opens unseeded. Its account picker,
       *  all-models switch and schedule field stay either way. */}
      {composer && (
        <LazyMassMessageComposer
          mode={composer}
          forcedAccountId={creatorId ?? undefined}
          onClose={() => setComposer(null)}
        />
      )}
    </>
  );
}
