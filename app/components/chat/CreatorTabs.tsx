"use client";


import { useLayoutEffect, useRef, type HTMLAttributes, type RefObject } from "react";
import { ArrowUpDown, Plus } from "lucide-react";

import { CreatorPlatformBadge } from "@/components/shell/PlatformSwitcher";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { useScope } from "@/contexts/ScopeContext";
import { useCreatorWarmUp } from "@/hooks/useCreatorWarmUp";
import { useLiveMark } from "@/hooks/useDataAge";
import { useOfNotifCount } from "@/hooks/useOfNotifCount";
import { useReorder } from "@/hooks/useReorder";
import { useOnScreenLease } from "@/hooks/useViewLease";
import { MP } from "@/lib/messagesPro";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import type { LiveMark } from "./dataAge";
import { MENU, MENU_ITEM } from "./MenuParts";
import { OpenInNewWindowMenu } from "./OpenInNewWindowMenu";
import { amberTitle, type AmberCircle } from "./amberCircle";
import { circleTitle, type RedCircle } from "./redCircle";
import { GreyMiniBadge, NotifMiniBadge, OweMiniBadge, UnreadMiniBadge } from "./UnreadMiniBadge";
import { useCreatorTabs, useShownCreatorTabs, type CreatorSort, type CreatorTabsStore } from "./useCreatorTabs";
import { useFanListMenu } from "./useFanListMenu";

const G = MP.creatorTabs;
const O = MP.ours.CreatorTabs;
const DROP_MARK = { before: O.dropMarkBefore, after: O.dropMarkAfter } as const;

function creatorWindowHref(accountId: string): string {
  return `/messages-pro?account=${encodeURIComponent(accountId)}`;
}

function MarkDot({ mark }: { mark: LiveMark }) {
  return (
    <span
      data-live-mark={mark.kind}
      className={cn(O.liveMark, "ring-[var(--inf-tab,var(--color-panel))]", mark.kind === "dead" ? "bg-err" : "bg-warn")}
    />
  );
}

function MarkWords({ mark }: { mark: LiveMark | null }) {
  return mark && <>{" "}<span className="sr-only">{mark.srText}</span></>;
}

type FocusTarget = { tab: string } | "add" | null;

export function CreatorTabs() {
  const store = useCreatorTabs();
  const { ready, close, reopen, reorder, sort, setSort } = store;
  const { open, circles, ambers } = useShownCreatorTabs(store);
  const track = useOnScreenLease("strip");
  const { scope, setScope } = useScope();
  const { warm, hoverThen, clearHover } = useCreatorWarmUp();
  const activeId = scope.kind === "model" ? scope.accountId : null;

  const tabRefs = useRef(new Map<string, HTMLButtonElement>());
  const addRef = useRef<HTMLButtonElement | null>(null);
  const focusNext = useRef<FocusTarget>(null);
  useLayoutEffect(() => {
    const target = focusNext.current;
    if (!target) return;
    focusNext.current = null;
    (target === "add" ? addRef.current : tabRefs.current.get(target.tab))?.focus();
  });

  const pick = (accountId: string) => {
    clearHover();
    setScope({ kind: "model", accountId });
    warm(accountId);
  };

  const closeTab = (accountId: string) => {
    const left = open.filter((a) => a.id !== accountId);
    close(accountId);
    if (left.length === 0) {
      focusNext.current = "add";
      return;
    }
    const stillActive = left.find((a) => a.id === activeId);
    const next = stillActive ?? left[0];
    if (accountId === activeId) pick(next.id);
    focusNext.current = { tab: next.id };
  };

  const drag = useReorder(open, (next) => reorder(next.map((a) => a.id)), (a) => a.id);

  const reopenTab = (accountId: string) => {
    reopen(accountId);
    pick(accountId);
    focusNext.current = { tab: accountId };
  };

  return (
    <>
      <div role="tablist" aria-label="Creator tabs" className={cn(G.strip, "flex items-end min-w-0 overflow-x-auto no-scrollbar")}>
        {open.map((a, idx) => {
          const from = drag.draggingIndex;
          const dropMark = from === null || from === idx || drag.dragOverIndex !== idx
            ? null
            : idx < from ? "before" : "after";
          return (
            <CreatorTab
              key={a.id}
              account={a}
              circle={circles[a.id]}
              amber={ambers[a.id]}
              active={a.id === activeId}
              dragging={from === idx}
              dropMark={dropMark}
              dragProps={{
                draggable: true,
                onDragStart: (e) => drag.onDragStart(e, idx),
                onDragOver: (e) => drag.onDragOver(e, idx),
                onDrop: (e) => drag.onDrop(e, idx),
                onDragEnd: drag.onDragEnd,
              }}
              onMove={(dir) => drag.onKeyboardMove(idx, dir)}
              tabRef={(el) => {
                if (el) tabRefs.current.set(a.id, el);
                else tabRefs.current.delete(a.id);
              }}
              leaseRef={track(a.id)}
              onPick={() => pick(a.id)}
              onClose={() => closeTab(a.id)}
              onHover={() => hoverThen(() => warm(a.id))}
              onHoverEnd={clearHover}
            />
          );
        })}
      </div>
      {ready && open.length === 0 && (
        <span className={cn(G.empty, "whitespace-nowrap text-fg-dim")}>
          {store.closed.length > 0
            ? "All creator tabs closed — use “+ Add a Creator”"
            : "No creators on this relay"}
        </span>
      )}
      <AddCreator open={open} closed={store.closed} addRef={addRef} onPick={reopenTab} />
      <SortTabs sort={sort} onSort={setSort} />
    </>
  );
}

function CreatorTab({
  account, circle, amber, active, dragging, dropMark, dragProps, onMove, tabRef, leaseRef, onPick, onClose, onHover, onHoverEnd,
}: {
  account: AccountMeta;
  circle: RedCircle;
  amber: AmberCircle;
  active: boolean;
  dragging: boolean;
  dropMark: keyof typeof DROP_MARK | null;
  dragProps: Pick<HTMLAttributes<HTMLDivElement>,
    "draggable" | "onDragStart" | "onDragOver" | "onDrop" | "onDragEnd">;
  onMove: (dir: -1 | 1) => void;
  tabRef: (el: HTMLButtonElement | null) => void;
  leaseRef: (el: Element | null) => void;
  onPick: () => void;
  onClose: () => void;
  onHover: () => void;
  onHoverEnd: () => void;
}) {
  const name = account.nickname || account.id;
  const { count: notifs } = useOfNotifCount(account.session_dead_at ? null : account.id);
  const mark = useLiveMark(account);
  const title = [name, circleTitle(circle), amberTitle(amber), mark?.title].filter(Boolean).join(" — ");
  return (
    <OpenInNewWindowMenu href={creatorWindowHref(account.id)}>
      <div
        {...dragProps}
        ref={leaseRef}
        className={cn(
          G.tab,
          "flex flex-none items-center",
          active
            ? "bg-accent/15 border-accent/55 text-fg"
            : "bg-[var(--inf-tab,var(--color-panel))] border-transparent text-fg hover:bg-bg-elev-1",
          (active || dropMark) && "inset-shadow-accent",
          dropMark ? DROP_MARK[dropMark] : active && G.tabActive,
          dragging && "opacity-40",
        )}
      >
        <button
          ref={tabRef}
          type="button"
          role="tab"
          aria-selected={active}
          onClick={onPick}
          onKeyDown={(e) => {
            if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
            e.preventDefault();
            onMove(e.key === "ArrowLeft" ? -1 : 1);
          }}
          onMouseEnter={onHover}
          onMouseLeave={onHoverEnd}
          onFocus={onHover}
          onBlur={onHoverEnd}
          title={title}
          className={cn(O.tabPick, "flex min-w-0 h-full items-center")}
        >
          <span aria-hidden className="relative flex flex-none">
            <span className={cn(G.avatar, "overflow-hidden flex-none")}>
              <AccountAvatarPicture account={account} letters={2} initialClassName="" />
            </span>
            {mark && <MarkDot mark={mark} />}
          </span>
          <span className={cn(G.name, "min-w-0 truncate")}>{name}</span>
          <CreatorPlatformBadge account={account} always />
          {circle.kind === "count" && <UnreadMiniBadge count={circle.text} />}
          {circle.kind === "grey" && <GreyMiniBadge />}
          {amber.kind !== "none" && <OweMiniBadge count={amber.kind === "count" ? amber.text : null} />}
          {notifs > 0 && <NotifMiniBadge count={notifs} />}
          <MarkWords mark={mark} />
        </button>
        {/* Sibling of the tab, not inside it: a button cannot nest in a button and would join the tab's accessible name. */}
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${name}`}
          title="Close this tab (reopen from + Add a Creator)"
          className={cn(G.close, "flex-none grid place-items-center text-fg-dim hover:text-fg")}
        >
          <span aria-hidden>✕</span>
        </button>
      </div>
    </OpenInNewWindowMenu>
  );
}

function AddCreator({
  open, closed, addRef, onPick,
}: {
  open: AccountMeta[];
  closed: CreatorTabsStore["closed"];
  addRef: RefObject<HTMLButtonElement | null>;
  onPick: (accountId: string) => void;
}) {
  const { open: menuOpen, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const rows = [
    ...open.map((account) => ({ account, meta: "open" })),
    ...closed.map((account) => ({ account, meta: "add" })),
  ];
  return (
    <div ref={ref} className="relative self-center flex-none">
      <button ref={addRef} type="button" {...triggerProps} className={cn(MP.windowHeader.addCreator, "flex items-center whitespace-nowrap text-fg")}>
        <Plus aria-hidden className={MP.windowHeader.addCreatorIcon} />
        Add a Creator
      </button>
      {menuOpen && (
        <section
          {...menuProps}
          aria-label="Creator picker"
          className={cn(MENU, O.pickerPlace)}
        >
          <div className={cn(MP.menu.head, "uppercase text-fg-dim")}>Creators on this relay ({rows.length})</div>
          {rows.map(({ account, meta }) => (
            <PickerRow key={account.id} account={account} meta={meta} onPick={() => { setOpen(false); onPick(account.id); }} />
          ))}
        </section>
      )}
    </div>
  );
}

function PickerRow({ account, meta, onPick }: { account: AccountMeta; meta: string; onPick: () => void }) {
  const mark = useLiveMark(account);
  return (
    <button type="button" onClick={onPick} title={mark?.title} className={MENU_ITEM}>
      <span aria-hidden className="relative flex flex-none">
        <span className={cn(MP.menu.avatar, "overflow-hidden flex-none")}>
          <AccountAvatarPicture account={account} letters={2} initialClassName="" />
        </span>
        {mark && <MarkDot mark={mark} />}
      </span>
      <span className="min-w-0 truncate">{account.nickname || account.id}</span>
      <CreatorPlatformBadge account={account} always />
      {" "}
      <span className={cn(MP.menu.meta, "ml-auto flex-none text-fg-dim")}>{meta}</span>
      <MarkWords mark={mark} />
    </button>
  );
}

const SORT_LABEL: Record<CreatorSort, string> = {
  custom: "Custom order",
  unread: "Most unread first",
  az: "A – Z",
  za: "Z – A",
};

function SortTabs({ sort, onSort }: { sort: CreatorSort; onSort: (sort: CreatorSort) => void }) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  return (
    <div ref={ref} className="relative self-center flex-none">
      <button
        type="button"
        {...triggerProps}
        aria-label="Sort creator tabs"
        title={`Sort creator tabs: ${SORT_LABEL[sort]}`}
        className={cn(MP.windowHeader.addCreator, "flex items-center text-fg-dim hover:text-fg")}
      >
        <ArrowUpDown aria-hidden className={MP.windowHeader.addCreatorIcon} />
      </button>
      {open && (
        <section {...menuProps} aria-label="Sort creator tabs" className={cn(MENU, O.pickerPlace)}>
          {(Object.keys(SORT_LABEL) as CreatorSort[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={sort === key}
              onClick={() => { setOpen(false); onSort(key); }}
              className={MENU_ITEM}
            >
              <span aria-hidden className="w-4 text-center">{sort === key ? "✓" : ""}</span>
              <span>{SORT_LABEL[key]}</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
