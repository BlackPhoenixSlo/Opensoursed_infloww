"use client";


import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "lucide-react";

import PlatformSwitcher, { usePlatformUnread } from "@/components/shell/PlatformSwitcher";
import { rosterUnreadText } from "@/lib/format";
import { Share04Line } from "@/components/shell/inflowwIcons";
import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { useFlags } from "@/components/shell/useFlags";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import {
  POPOUT_FEATURES,
  SIDEBAR_FOOTER,
  drawnSidebar,
  isDivider,
  isGroup,
  isPopoutRoute,
  onPopoutClick,
  sidebarFor,
  sidebarHref,
  visibleLinks,
  type NavGroup,
  type NavLink,
  type NavNode,
} from "@/lib/nav";
import { usePlatform } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { version } from "@/package.json";

const ROW = "flex items-center gap-2 h-9 rounded-lg text-[16px] font-medium transition-colors";
const ROW_IDLE = "text-nav-fg hover:bg-nav-hover";
const ROW_ACTIVE = "bg-nav-hover text-nav-fg-active";

function activeHref(pathname: string, links: NavLink[]): string | null {
  let best: string | null = null;
  for (const { href } of links) {
    const hit = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");
    if (hit && (!best || href.length > best.length)) best = href;
  }
  return best;
}

function flatten(nodes: NavNode[]): NavLink[] {
  return nodes.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
}

export default function Sidebar({
  id,
  className,
  onNavigate,
  collapsed = false,
}: {
  id?: string;
  className?: string;
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const pathname = usePathname() ?? "/";
  const filter = {
    chatterOnly: useIsChatterOnly(), grantedPages: useGrantedPages(), flags: useFlags(),
  };
  const platform = usePlatform();
  const unread = usePlatformUnread()[platform];
  const nodes = drawnSidebar(sidebarFor(platform), filter);
  const footer = visibleLinks(SIDEBAR_FOOTER, filter);
  const active = activeHref(sidebarHref(pathname, filter.grantedPages), [...flatten(nodes), ...footer]);
  const where = `${platform} ${active}`;
  const [choice, setChoice] = useState<{ label: string | null; where: string } | null>(null);
  const openGroup = choice?.where === where ? choice.label : undefined;

  const link = (l: NavLink, sub = false, footer = false) => {
    const Icon = l.icon;
    // Messages Pro (and a page inside it) opens in its own window and this page stays put.
    const onClick = (e: React.MouseEvent) => {
      if (isPopoutRoute(l.href)) onPopoutClick(e, l.href);
      onNavigate?.();
    };
    if (collapsed) {
      return (
        <Link
          key={l.href}
          href={l.href}
          onClick={onClick}
          title={l.label}
          aria-label={l.label}
          aria-current={active === l.href ? "page" : undefined}
          className={cn(ROW, "w-9 justify-center shrink-0", active === l.href ? ROW_ACTIVE : ROW_IDLE)}
        >
          {Icon && <Icon aria-hidden className="w-5 h-5 shrink-0" />}
        </Link>
      );
    }
    const row = (
      <Link
        key={l.href}
        href={l.href}
        onClick={onClick}
        aria-current={active === l.href ? "page" : undefined}
        className={cn(
          ROW,
          "min-w-0",
          footer ? "px-2" : "px-3",
          sub && "pl-4",
          l.popout && "h-11 pr-[68px]",
          active === l.href ? ROW_ACTIVE : ROW_IDLE,
        )}
      >
        {Icon && <Icon aria-hidden className="w-5 h-5 shrink-0" />}
        <span className="truncate">{l.label}</span>
      </Link>
    );
    if (!l.popout) return row;
    return (
      <div key={l.href} className="relative flex flex-col">
        {row}
        <div className="absolute right-3 inset-y-0 flex items-center gap-2 pointer-events-none">
          <span
            aria-label={`${unread.count} unread`}
            className="min-w-4 h-4 px-1 rounded-full bg-pink text-white text-[12px] leading-4 text-center"
          >
            {rosterUnreadText(unread.count)}
          </span>
          <button
            type="button"
            onClick={() => {
              window.open(l.href, "_blank", POPOUT_FEATURES);
              onNavigate?.();
            }}
            title={`Open another ${l.label} window`}
            aria-label={`Open another ${l.label} window`}
            className="pointer-events-auto w-7 h-7 rounded-md bg-nav-surface hover:bg-nav-hover grid place-items-center text-nav-fg-active"
          >
            <Share04Line aria-hidden className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  };

  return (
    <aside
      id={id}
      className={cn(
        "max-w-full shrink-0 flex-col bg-chrome pt-3 pb-4 transition-[width] duration-200",
        collapsed ? "w-[60px] px-3 items-center" : "w-64 px-3",
        className,
      )}
    >
      <PlatformSwitcher collapsed={collapsed} />

      <nav
        aria-label="Main"
        className={cn("flex-1 min-h-0 overflow-y-auto no-scrollbar flex flex-col gap-2", collapsed && "items-center")}
      >
        {nodes.map((n, i) => {
          if (isDivider(n)) return <div key={`d${i}`} className="shrink-0 self-stretch h-px bg-nav-surface my-2" />;
          if (!isGroup(n)) return link(n);
          if (collapsed) return <RailGroup key={n.label} group={n} active={active} onNavigate={onNavigate} />;
          const holdsActive = n.children.some((c) => c.href === active);
          const open = openGroup === undefined ? holdsActive : openGroup === n.label;
          const Icon = n.icon;
          return (
            <div key={n.label}>
              <button
                type="button"
                onClick={() => setChoice({ label: open ? null : n.label, where })}
                aria-expanded={open}
                className={cn(ROW, "w-full px-3", holdsActive ? ROW_ACTIVE : ROW_IDLE)}
              >
                <Icon aria-hidden className="w-5 h-5 shrink-0" />
                <span className="flex-1 text-left truncate">{n.label}</span>
                <ChevronDown aria-hidden className={cn("w-5 h-5 transition-transform", open && "rotate-180")} />
              </button>
              {open && (
                <div className="flex flex-col gap-2 pl-4 mt-2">
                  {n.children.map((c) => link(c, true))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className={cn("shrink-0 self-stretch flex flex-col gap-2 pt-4 mt-2 border-t border-nav-surface", collapsed && "items-center")}>
        {footer.map((l) => link(l, false, true))}
        {!collapsed && <div className="text-[14px] font-medium text-nav-fg px-3 pt-2">Version {version}</div>}
      </div>
    </aside>
  );
}

// rc-menu's subMenuOpenDelay / subMenuCloseDelay.
const FLYOUT_DELAY_MS = 100;
// Infloww keeps the flyout under its own top bar: Math.max(54, ...).
const flyoutMinTop = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--chrome-top")) || 52;
const FLYOUT_MAX_HEIGHT = 400;

function RailGroup({ group, active, onNavigate }: { group: NavGroup; active: string | null; onNavigate?: () => void }) {
  const Icon = group.icon;
  const holdsActive = group.children.some((c) => c.href === active);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [pos, setPos] = useState<{ top: number; left: number; maxHeight: number } | null>(null);
  const open = pos !== null;
  const flyoutId = `rail-${group.label.replace(/\W+/g, "-").toLowerCase()}`;

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const show = () => {
    const r = triggerRef.current?.getBoundingClientRect();
    if (!r) return;
    const want = Math.min(FLYOUT_MAX_HEIGHT, group.children.length * 44 + 8);
    const top = Math.max(flyoutMinTop(), Math.min(r.top, window.innerHeight - want - 8));
    setPos({ top, left: r.right + 4, maxHeight: Math.min(FLYOUT_MAX_HEIGHT, window.innerHeight - top - 8) });
  };
  const hide = () => setPos(null);
  const later = (fn: () => void) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(fn, FLYOUT_DELAY_MS);
  };
  const hover = { onMouseEnter: () => later(show), onMouseLeave: () => later(hide) };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "Escape" || !open) return;
    hide();
    triggerRef.current?.focus();
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        {...hover}
        onClick={() => {
          window.clearTimeout(timer.current);
          if (open) hide();
          else show();
        }}
        onKeyDown={onKeyDown}
        title={group.label}
        aria-label={group.label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? flyoutId : undefined}
        className={cn(ROW, "w-9 justify-center shrink-0", holdsActive || open ? ROW_ACTIVE : ROW_IDLE)}
      >
        <Icon aria-hidden className="w-5 h-5 shrink-0" />
      </button>
      {open &&
        createPortal(
          <div
            id={flyoutId}
            role="menu"
            aria-label={group.label}
            {...hover}
            onKeyDown={onKeyDown}
            style={{ top: pos.top, left: pos.left, maxHeight: pos.maxHeight }}
            className="fixed z-50 min-w-[180px] overflow-y-auto flex flex-col gap-2 p-2 rounded-lg border border-nav-surface bg-chrome shadow-lg"
          >
            {group.children.map((c) => (
              <Link
                key={c.href}
                href={c.href}
                role="menuitem"
                onClick={() => {
                  hide();
                  onNavigate?.();
                }}
                aria-current={active === c.href ? "page" : undefined}
                className={cn(ROW, "shrink-0 px-3 whitespace-nowrap", active === c.href ? ROW_ACTIVE : ROW_IDLE)}
              >
                {c.label}
              </Link>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
