"use client";

/**
 * TopBar — Infloww's top bar (docs/infloww-screens.md §1.2; header `index$c`,
 * bundle @11162567): sidebar collapse (the drawer's hamburger below lg), our
 * wordmark and, while it runs, the free trial's days left, then on the right
 * the status pill (`StatusPill`, static green "Operational"), our error
 * triage badge (`ErrorBadge`, an extra: the last 24h of /admin/errors), the
 * user's time zone (`TimeZoneLabel`), the SFW switch, the one notifications
 * bell (`HeaderBell`: OnlyFans notifications, plus for the owner the agency
 * notification centre as the panel's "Agency" tab), the Clock button
 * (`ClockButton`, while the caller may clock; Infloww's `HeaderSignButton`)
 * and the avatar menu (theme; "Log out"). Infloww's Referrals and
 * Leaderboard are left out: we have neither. No model filter: a page that
 * shows one creator picks it in the page (OF Manager's column, Messages Pro's
 * Creator tabs, the Growth and Settings pickers).
 *
 * The items are Infloww's borderless filled tiles (`HEADER_TILE`, its
 * `HBButton size="generous"`: 36px, 8px radius, the 9% white fill), 8px apart
 * (`headerRightPart`); the pill is its smaller `size="moderate"` button; SFW
 * is its bare "SFW" caption over a small switch (`SfwSwitchInner`). 52px tall
 * (36px plus 8px above and below), borderless on the black chrome; while the
 * trial runs the "free trial has started" banner sits under it in the same
 * sticky block. `--chrome-top` (globals.css) is that block's height:
 * `.h-chat`, the docked sidebar and the fixed dropdowns are sized against it.
 * Below lg the status pill, the error badge and the time zone hide; below sm
 * the wordmark and the Clock button's elapsed time hide, so 360px fits.
 */

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { useTheme } from "@/hooks/useTheme";
import { useSfw } from "@/hooks/useBlurMode";
import { NotificationBell } from "@/components/NotificationBell";
import { AgencyFeed, useAgencyUnread } from "@/components/AgencyNotifications";
import { ErrorBadge } from "@/components/ErrorBadge";
import ClockButton from "@/components/shifts/ClockButton";
import { FreeTrialBadge, FreeTrialBanner } from "@/components/shell/FreeTrial";
import { Globe04Line, InfoCircleLine, SidebarLine, SidebarSolid } from "@/components/shell/inflowwIcons";
import { HEADER_TILE, HEADER_TILE_ICON } from "@/components/shell/headerTile";
import { useAgencyTimeZone } from "@/lib/appliedSettings";
import { zoneOffsetNow } from "@/lib/creatorClock";
import { cn } from "@/lib/utils";

/** "UTC+02:00" for an offset in minutes east of UTC. */
function utcOffsetLabel(mins: number): string {
  const sign = mins < 0 ? "-" : "+";
  const abs = Math.abs(mins);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `UTC${sign}${hh}:${mm}`;
}
const noSubscribe = () => () => {};

export default function TopBar({
  onToggleSidebar,
  sidebarExpanded,
  sidebarId,
  sidebarLocked,
}: {
  onToggleSidebar: () => void;
  /** Sidebar column (lg+) or drawer (below lg) is showing. */
  sidebarExpanded: boolean;
  sidebarId: string;
  /** Held as the icon rail (OF Manager): the toggle is disabled. */
  sidebarLocked?: boolean;
}) {
  const [sfw, toggleSfw] = useSfw();

  return (
    // flow-root: the banner's bottom margin stays inside the black block.
    <div className="sticky top-0 z-30 bg-chrome flow-root">
      <header className="h-[52px] flex items-center gap-2 sm:gap-4 px-3">
        <SidebarToggle
          onToggleSidebar={onToggleSidebar}
          sidebarExpanded={sidebarExpanded}
          sidebarId={sidebarId}
          sidebarLocked={sidebarLocked}
        />
        {/* Below sm the wordmark gives way to the right-hand controls (360px). */}
        <Link href="/" className="hidden sm:inline font-semibold text-fg tracking-tight shrink-0">
          Inflowwww
        </Link>
        <FreeTrialBadge />

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2 min-w-0">
          <StatusPill />
          <ErrorBadge />
          <TimeZoneLabel />
          {/* SFW = blur media everywhere (Infloww's SFW mode). Flips between off
           *  and the last-used blurred variant; the chat gear stays in sync. */}
          <SfwSwitch on={sfw} onToggle={toggleSfw} />
          <HeaderBell />
          <ClockButton />
          <AvatarMenu />
        </div>
      </header>
      <FreeTrialBanner />
    </div>
  );
}

/** Infloww's "Operational" status pill, first on the right. Static green:
 *  Infloww polls a status page and we have none (owner decision 2026-10-19);
 *  our errors are triaged from `ErrorBadge` beside it. Its `HBButton
 *  size="moderate"`: 28px, 6px radius, 6px 9px padding, 500 14px, a 12px dot
 *  5px before the text (`.hb-button--size-moderate`, `_icon_18xnb_6`). From lg up. */
function StatusPill() {
  return (
    <span className="hidden lg:flex h-7 px-[9px] items-center gap-[5px] rounded-[6px] bg-nav-surface text-[14px] font-medium text-nav-fg-active whitespace-nowrap shrink-0">
      <span aria-hidden className="size-3 rounded-full bg-ok" />
      Operational
    </span>
  );
}

/** Infloww's SFW (`SfwSwitchInner`): no box, the "SFW" caption
 *  (500 12px/14px, 38% white while off, white while on) stacked over its
 *  small switch (`.hb-switch-size-small`: a 24×16 pill on the 9% fill, an
 *  8px white knob 4px in, moving 8px when on). */
function SfwSwitch({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex flex-col items-start shrink-0"
      aria-label="SFW"
      aria-pressed={on}
      title={on ? "SFW on: media blurred" : "SFW off"}
    >
      <span aria-hidden className={cn("text-[12px] leading-[14px] font-medium", on ? "text-nav-fg-active" : "text-nav-fg-active/38")}>
        SFW
      </span>
      <span aria-hidden className={cn("relative block w-6 h-4 rounded-full transition-colors", on ? "bg-accent" : "bg-nav-surface")}>
        <span className={cn("absolute top-1 size-2 rounded-full bg-white transition-[left]", on ? "left-3" : "left-1")} />
      </span>
    </button>
  );
}

/** The header's one bell: OnlyFans notifications, and for the owner the
 *  agency notification centre folded in as the panel's "Agency" tab. */
export function HeaderBell() {
  const agencyUnread = useAgencyUnread();
  return (
    <NotificationBell agency={agencyUnread == null ? undefined : { unread: agencyUnread, panel: <AgencyFeed /> }} />
  );
}

/** The sidebar toggle: Infloww's 32x28 button, the solid sidebar icon on a
 *  5.5% wash while the sidebar shows, the outline one while folded. */
function SidebarToggle({
  onToggleSidebar,
  sidebarExpanded,
  sidebarId,
  sidebarLocked = false,
}: {
  onToggleSidebar: () => void;
  sidebarExpanded: boolean;
  sidebarId: string;
  sidebarLocked?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onToggleSidebar}
      disabled={sidebarLocked}
      className={cn(
        "w-8 h-7 rounded-lg shrink-0 grid place-items-center text-nav-fg-active hover:bg-nav-hover disabled:opacity-40 disabled:pointer-events-none",
        sidebarExpanded && "bg-nav-hover",
      )}
      title={sidebarLocked ? "The sidebar stays collapsed on OF Manager" : "Toggle sidebar"}
      aria-label="Toggle sidebar"
      aria-expanded={sidebarExpanded}
      aria-controls={sidebarId}
    >
      {sidebarExpanded ? <SidebarSolid aria-hidden className="w-5 h-5" /> : <SidebarLine aria-hidden className="w-5 h-5" />}
    </button>
  );
}

/** The Agency's regular time zone (`preferences.tz` from the Applied settings
 *  read) as "UTC+02:00", or the browser's while none is stored, loaded or
 *  readable; from lg up. */
// ASSUMPTION: while the read loads or fails the label shows the browser's zone, as before this read
// existed. Rung 4: no blank or broken label. Overturned if a brief browser-zone flash is unwanted.
export function TimeZoneLabel() {
  const agency = useAgencyTimeZone();
  // Server render has no time zone; the client fills it in after hydration.
  const hydrated = useSyncExternalStore(noSubscribe, () => true, () => false);
  const zone = hydrated ? zoneOffsetNow(agency) : null;
  if (!zone) return null;
  const tz = utcOffsetLabel(zone.minutes);
  // Infloww's `UTCRender`: a tile with `Globe04Line`, the offset and an
  // `InfoCircleLine` 4px after it carrying the tip; a click opens Your Preferences.
  return (
    <Link href="/settings/preferences" className={cn(HEADER_TILE, "hidden lg:inline-flex tabular-nums")} title="Your time zone">
      <Globe04Line aria-hidden className={HEADER_TILE_ICON} />
      {tz}
      <span title="The regular time zone you selected in Settings" className="-ml-1 inline-flex">
        <InfoCircleLine aria-hidden className={HEADER_TILE_ICON} />
      </span>
    </Link>
  );
}

/** The avatar and its menu (theme; log out). Clocking is the top bar's
 *  `ClockButton`, as Infloww's. */
export function AvatarMenu() {
  const { user, logout } = useUser();
  const { chatter, logout: chatterLogout } = useChatter();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  // The User cookie wins precedence: the menu names the owner while both are set.
  const name = user?.username ?? chatter?.username ?? null;

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const item = "w-full text-left px-3 h-10 flex items-center gap-2 rounded-lg text-sm hover:bg-bg-elev-1";

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-[34px] h-[34px] text-sm rounded-full bg-accent text-white font-semibold grid place-items-center"
        title={name ? `@${name}` : "Account"}
        aria-label="Account menu"
        aria-expanded={open}
      >
        {(name ?? "?").slice(0, 1).toUpperCase()}
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-60 bg-panel border border-border rounded-xl shadow-xl p-1 z-40">
          {name && <div className="px-3 py-2 text-xs text-fg-dim truncate">@{name}</div>}
          <button type="button" className={item} onClick={toggle}>
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
          {(user || chatter) && (
            <button
              type="button"
              className={cn(item, "text-err")}
              onClick={() => { setOpen(false); void (user ? logout() : chatterLogout()); }}
            >
              Log out
            </button>
          )}
        </div>
      )}
    </div>
  );
}
