"use client";

/**
 * AppShell — Infloww's chrome: top bar across the full width, the sidebar on
 * the left, the page on the right in a panel with a rounded top-left corner
 * set into the black chrome. At lg+ the sidebar is a sticky column the
 * top bar's collapse button folds to Infloww's 60px icon rail (the icons
 * stay); below lg it is an off-canvas drawer (a
 * Radix dialog: focus trap, Escape, backdrop click) opened from that same
 * button, or by a swipe right that starts anywhere on the page but the OS's
 * edge zones, outside any open dialog (`useSwipe`). The drawer closes on any
 * route change, or on a swipe left on it or its backdrop.
 *
 * Messages Pro (`isPopoutRoute`) is a window of its own, as in Infloww: the
 * sidebar opens it with `openPopout`, and on its routes the shell renders
 * only the page's main element: no top bar, no sidebar, no drawer. A Deep
 * link or an old bookmark lands in that same layout. Its `ClockHeartbeat`
 * stands in for the top bar's Clock button, so input there renews an open
 * Clock event. The desktop app's main window never stays on it
 * (`LeaveDesktopMainWindow`).
 *
 * On OF Manager (`hasCreatorColumn`) the docked sidebar is that icon rail,
 * locked: the toggle is disabled from lg up, as Infloww's OfManagerWrap
 * `toggleMenu(true, true)` does (docs/infloww-of-manager-rea.md §1.4). It is
 * read from the path, so the server render already draws the rail. Leaving OF
 * Manager brings back the sidebar as the user had it; below lg the drawer is
 * the full sidebar as everywhere. Settings locks the same rail: Infloww draws
 * its Settings as an overlay right of the 60px rail.
 *
 * Outside Messages Pro an expired free trial shows its nag once per
 * mount, i.e. once per app start (`FreeTrialExpiredModal`).
 *
 * In every window PlatformSync keeps the platform, the page and the scope
 * agreeing (a route, the selector, another window's switch); outside Messages
 * Pro PlatformGate prompts a Fansly login in Fansly mode when no Fansly
 * account has a session.
 *
 * Either way the page sits behind `DeniedPageGate`: a page the Permission
 * role denies renders the denied-page panel instead (spec phase-04, story 34).
 */

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";

import { hasCreatorColumn } from "@/components/of-manager/OfManagerChrome";
import DeniedPageGate from "@/components/shell/DeniedPage";
import { DesktopUpdateBanner } from "@/components/shell/DesktopUpdateBanner";
import { FreeTrialExpiredModal } from "@/components/shell/FreeTrial";
import PlatformGate, { PlatformSync } from "@/components/shell/PlatformGate";
import Sidebar from "@/components/shell/Sidebar";
import TopBar from "@/components/shell/TopBar";
import { ClockHeartbeat } from "@/components/shifts/ClockButton";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { OS_EDGE_PX, useSwipe } from "@/hooks/useSwipe";
import { isPopoutRoute, openPopout, POPOUT_WINDOW } from "@/lib/nav";

const SIDEBAR_ID = "app-sidebar";
const DRAWER_ID = "app-sidebar-drawer";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const docked = useIsDesktop();
  // OF Manager and Settings (Infloww's full-window Settings overlay) hold the docked sidebar as the icon rail.
  const ofRail = hasCreatorColumn(pathname) || pathname === "/settings" || pathname.startsWith("/settings/");
  const locked = docked && ofRail;
  const [collapsed, setCollapsed] = useState(false);
  // The path the drawer was opened on. Any navigation (link, back/forward)
  // changes the path and so closes it; widening past lg closes it too.
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const drawerOpen = !docked && drawerPath === pathname;
  const setDrawerOpen = (open: boolean) => setDrawerPath(open ? pathname : null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const popout = isPopoutRoute(pathname);
  useSwipe(null, {
    enabled: !docked && !popout && !drawerOpen, dir: "right", onSwipe: () => setDrawerPath(pathname),
    edgeGuard: OS_EDGE_PX, ignoreWhile: "[role='dialog'], [aria-modal='true']",
  });
  // The drawer and its backdrop cover the page, so the whole document listens while it is open.
  useSwipe(null, { enabled: drawerOpen, dir: "left", onSwipe: () => setDrawerPath(null), follow: drawerRef });

  // Messages Pro has no top bar, so the shell offset `.h-chat` subtracts
  // (`--shell-top`, globals.css) is 0 and the panes fill the window.
  if (popout) {
    return (
      <main className="min-w-0" style={{ ["--shell-top" as string]: "0px" }}>
        <LeaveDesktopMainWindow pathname={pathname} />
        <PlatformSync />
        <ClockHeartbeat />
        <DeniedPageGate>{children}</DeniedPageGate>
      </main>
    );
  }

  return (
    <>
      <TopBar
        onToggleSidebar={() => {
          if (locked) return;
          if (docked) setCollapsed((c) => !c);
          else setDrawerOpen(!drawerOpen);
        }}
        sidebarExpanded={locked ? false : docked ? !collapsed : drawerOpen}
        sidebarId={docked ? SIDEBAR_ID : DRAWER_ID}
        sidebarLocked={locked}
      />
      <div className="flex bg-chrome">
        <Sidebar
          id={SIDEBAR_ID}
          collapsed={ofRail || collapsed}
          className="hidden lg:flex sticky top-[var(--chrome-top)] h-[calc(100dvh-var(--chrome-top))]"
        />
        <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="lg:hidden fixed inset-0 z-40 bg-black/50" />
            <Dialog.Content
              ref={drawerRef}
              id={DRAWER_ID}
              aria-describedby={undefined}
              className="lg:hidden fixed inset-y-0 left-0 z-50 flex max-w-[85vw] outline-none"
            >
              <Dialog.Title className="sr-only">Menu</Dialog.Title>
              <Sidebar
                className="flex h-dvh pb-[max(1rem,env(safe-area-inset-bottom))]"
                onNavigate={() => setDrawerOpen(false)}
              />
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
        {/* `overflow-clip`, not hidden: the window still scrolls, so sticky headers in the page hold. */}
        <main className="flex-1 min-w-0 bg-bg rounded-tl-xl overflow-clip">
          <DeniedPageGate>{children}</DeniedPageGate>
        </main>
      </div>
      <FreeTrialExpiredModal />
      <PlatformSync />
      <PlatformGate />
      <DesktopUpdateBanner />
    </>
  );
}

/**
 * The desktop app's main window has no address bar and no Back, so Messages Pro there (the shell's old `/inbox`
 * start, a restored route, a sign-in's `?next=`, a notification or app link) would leave no way to the rest of the
 * app. The main window is the one no window opened and not named `messages-pro`. A Deep link opens in the Messages
 * Pro window (`openPopout`), as a click would; then the main window loads the Dashboard.
 */
function LeaveDesktopMainWindow({ pathname }: { pathname: string }) {
  useEffect(() => {
    if (window.fasttShell?.isDesktop !== true || window.opener || window.name === POPOUT_WINDOW) return;
    if (pathname !== "/messages-pro") openPopout(`${pathname}${window.location.search}`);
    window.location.replace("/");
  }, [pathname]);
  return null;
}
