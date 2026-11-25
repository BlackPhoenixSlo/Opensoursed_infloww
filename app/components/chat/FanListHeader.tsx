"use client";


import { useId, useRef, useState, type ComponentProps } from "react";
import { Image as ImageIcon, Plus, Search } from "lucide-react";
import { LazyMassMessageComposer } from "@/components/compose/LazyMassMessageComposer";
import type { FanId } from "@/lib/fanId";
import { useCanOrFallback } from "@/hooks/useCan";
import { can, type Platform } from "@/lib/platform";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { ChatGallery } from "./ChatGallery";
import { MENU, MENU_ITEM } from "./MenuParts";
import { useFanListMenu } from "./useFanListMenu";

const G = MP.fanList;

const ICON_BUTTON = "grid place-items-center shrink-0 text-fg-dim hover:text-fg hover:bg-bg-elev-1";

type ComposerMode = NonNullable<ComponentProps<typeof LazyMassMessageComposer>["mode"]>;

type NewMenuItem = { label: string } & ({ composer: ComposerMode } | { href: string });

const NEW_MENU_ITEMS: readonly NewMenuItem[] = [
  { label: "Mass message", composer: "standard" },
  { label: "Message online fans", composer: "online" },
  { label: "Post", href: "/of-manager/new-post" },
];

function NewMenu({ mass, onCompose }: { mass: boolean; onCompose: (mode: ComposerMode) => void }) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const row = (item: NewMenuItem) =>
    "href" in item ? (
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
        title={mass ? "New: mass message, message online fans, or post" : "New: post"}
      >
        <Plus aria-hidden className={G.iconButtonIcon} />
      </button>
      {open && (
        <section {...menuProps} aria-label="New" className={cn(MENU, MP.ours.FanListHeader.menuPlace)}>
          {NEW_MENU_ITEMS.filter((item) => mass || "href" in item).map(row)}
        </section>
      )}
    </div>
  );
}

export function FanListHeader({
  title, creatorId, scopePlatforms, query, onQueryChange, galleryFan,
}: {
  title: string;
  creatorId: string | null;
  scopePlatforms: readonly Platform[];
  query: string;
  onQueryChange: (next: string) => void;
  galleryFan: { accountId: string; fanId: FanId } | null;
}) {
  const [galleryFor, setGalleryFor] = useState<typeof galleryFan>(null);
  const scoped = galleryFan?.accountId ?? creatorId;
  const scopedGallery = useCanOrFallback(scoped, "chat_media");
  const platformGallery = scopePlatforms.some((p) => can(p, "chat_media"));
  const showGallery = scoped ? scopedGallery : platformGallery;
  const [searchOpen, setSearchOpen] = useState(false);
  const [composer, setComposer] = useState<ComposerMode | null>(null);
  const searchButtonRef = useRef<HTMLButtonElement | null>(null);
  const searchRowId = useId();
  const closeSearch = () => {
    setSearchOpen(false);
    onQueryChange("");
    searchButtonRef.current?.focus();
  };
  return (
    <>
      <div role="group" aria-label="Fan List header" className={cn(G.head, "flex items-center border-[var(--inf-rule,var(--color-border))]")}>
        <h2 className={cn(G.title, "flex-1 min-w-0 truncate")}>{title}</h2>
        {showGallery && (
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
        )}
        <button
          ref={searchButtonRef}
          type="button"
          onClick={() => (searchOpen ? closeSearch() : setSearchOpen(true))}
          className={cn(G.iconButton, ICON_BUTTON)}
          aria-label="Search"
          title={searchOpen ? "Close search" : "Search chats by fan name or username"}
          aria-expanded={searchOpen}
          aria-controls={searchOpen ? searchRowId : undefined}
        >
          <Search aria-hidden className={G.iconButtonIcon} />
        </button>
        <NewMenu mass={scopePlatforms.some((p) => can(p, "mass_message"))} onCompose={setComposer} />
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
      {galleryFor && showGallery && (
        <ChatGallery accountId={galleryFor.accountId} fanId={galleryFor.fanId} onClose={() => setGalleryFor(null)} />
      )}
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
