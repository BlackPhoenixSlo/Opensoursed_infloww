/**
 * BootSkeleton: what a signed-in session sees while AuthGate waits on its principal probes. AuthGate draws it from
 * the server render on, so the HTML itself paints the page's frame (top bar, sidebar, the route's header, cards,
 * rows, chat list) with placeholder bars where the figures go, and the phone is never blank while the JS loads and
 * `/auth/me` answers (2026-10-28 dashboard-load: slow4g first paint at 3.4 s against the HTML at 0.6 s). The real
 * page replaces it whole; each page then shimmers its own figures until its reads land.
 *
 * No hooks and no data: the layout follows the path, and phone or desktop is CSS (`lg:`), so the server render and
 * hydration agree. Its classes mirror the shell's and the pages' (AppShell, TopBar, Sidebar, InflowwPageHeader,
 * IfCard, DashboardHeader, MessagesPro) so the swap does not jump. `data-boot-skeleton` marks it for slop's
 * first-paint check.
 */

import { FanListSkeleton } from "@/components/chat/FanListStates";
import { control, PERIOD_TABS, type DashboardControlKey } from "@/components/home/dashboardControls";
import { Skeleton, TableSkeleton } from "@/components/ui/Skeleton";
import { findNavLink, hasCreatorColumn, isPopoutRoute } from "@/lib/nav";
import { cn } from "@/lib/utils";

const label = (k: DashboardControlKey) => control(k).labels[0];
/** The shell's bars on the black chrome. */
const ON_CHROME = "bg-nav-surface";

export default function BootSkeleton({ pathname }: { pathname: string }) {
  if (isPopoutRoute(pathname)) {
    return (
      <Frame route="messages-pro">
        <main className="min-w-0" style={{ ["--shell-top" as string]: "0px" }}>
          <MessagesProBoot />
        </main>
      </Frame>
    );
  }
  const rail = hasCreatorColumn(pathname) || pathname === "/settings" || pathname.startsWith("/settings/");
  return (
    <Frame route={pathname === "/" ? "dashboard" : "page"}>
      <div className="sticky top-0 z-30 bg-chrome">
        <div className="h-[52px] flex items-center gap-2 sm:gap-4 px-3 in-data-[shell=mac]:pl-[84px]">
          <Skeleton className={cn("size-5", ON_CHROME)} />
          <Skeleton className={cn("hidden sm:block h-5 w-24", ON_CHROME)} />
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            <Skeleton className={cn("h-7 w-[46px]", ON_CHROME)} />
            <Skeleton className={cn("h-[34px] w-[60px] rounded-[10px]", ON_CHROME)} />
            <Skeleton className={cn("size-[34px] rounded-full", ON_CHROME)} />
          </div>
        </div>
      </div>
      <div className="flex bg-chrome">
        <div className={cn("hidden lg:flex sticky top-[var(--chrome-top)] h-[calc(100dvh-var(--chrome-top))] shrink-0",
          "flex-col gap-2 bg-chrome pt-3 pb-4 px-3", rail ? "w-[60px] items-center" : "w-64")}>
          {Array.from({ length: 11 }, (_, i) => (
            <Skeleton key={i} className={cn("h-9", rail ? "w-9" : "w-full", ON_CHROME)} />
          ))}
        </div>
        <main className="flex-1 min-w-0 min-h-[calc(100dvh-var(--chrome-top))] bg-bg rounded-tl-xl overflow-clip">
          {pathname === "/" ? <DashboardBoot /> : <PageBoot title={findNavLink(pathname)?.label} />}
        </main>
      </div>
    </Frame>
  );
}

function Frame({ route, children }: { route: string; children: React.ReactNode }) {
  return (
    <div data-boot-skeleton={route} aria-busy="true">
      <span role="status" className="sr-only">Loading</span>
      {children}
    </div>
  );
}

/** The Dashboard (`app/page.tsx`): the period tabs, the earnings card with its labels and a bar per figure, and the
 *  cards under it. */
function DashboardBoot() {
  return (
    <div className="min-h-dvh p-4">
      <div className="mb-4 flex flex-wrap items-center justify-end gap-3">
        <div className="flex w-full md:w-auto rounded-[4px] border border-border bg-bg-elev-1 p-1">
          {PERIOD_TABS.map((t) => (
            <span key={t.key}
              className="h-6 flex items-center justify-center whitespace-nowrap rounded-[4px] max-md:flex-1 px-1 md:px-5 text-[12px] text-fg-dim">
              {t.labels[0]}
            </span>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
        <section className="md:col-span-12 rounded-[12px] bg-bg-elev-1 px-6 pb-4 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[16px] font-medium text-fg">{label("title")}</h2>
            <Skeleton className="h-10 w-[140px] rounded-[6px]" />
          </div>
          <div className="mt-4 flex flex-col xl:flex-row">
            <div className="xl:flex-1 min-w-0 md:h-[177px] flex flex-col justify-center pl-6 py-4 md:py-0">
              <span className="w-[45px] h-[45px] rounded-full bg-accent" />
              <span className="text-[12px] leading-[15px] font-medium mt-[18px] mb-3 text-[#1890ff]">{label("total")}</span>
              <span className="h-[45px] flex items-center"><Skeleton className="h-[34px] w-32" /></span>
            </div>
            <div className="flex flex-col md:flex-row xl:flex-[3] min-w-0">
              {([["subscriptions", "tips"], ["posts", "referrals"], ["messages", "streams"]] as const).map(([a, b], i) => (
                <div key={a} className={cn(
                  "flex-1 min-w-0 md:h-[177px] flex flex-col justify-center gap-4 md:gap-[56px] py-4 md:py-0",
                  "border-t xl:border-t-0 md:border-l border-border", i === 0 && "md:border-l-0 xl:border-l")}>
                  {[a, b].map((k) => (
                    <div key={k} className="flex items-center justify-between gap-2 ml-[35.5px] mr-[38.5px]">
                      <div className="flex flex-col">
                        <span className="h-[28px] flex items-center"><Skeleton className="h-[21px] w-16" /></span>
                        <span className="text-[12px] leading-[17px] text-[#808080]">{label(k)}</span>
                      </div>
                      <Skeleton className="size-[45px] rounded-full" />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </section>
        <section className="md:col-span-4 xl:col-span-3 md:row-span-2 min-h-[320px] rounded-[12px] bg-bg-elev-1 px-6 pt-5">
          <Skeleton className="h-4 w-24" />
        </section>
        {[0, 1].map((i) => (
          <section key={i} className="md:col-span-8 xl:col-span-9 h-[200px] rounded-[12px] bg-bg-elev-1 px-6 pt-5">
            <Skeleton className="h-4 w-40" />
          </section>
        ))}
      </div>
    </div>
  );
}

/** Any other page: InflowwPageHeader's 48px header with the page's sidebar label, a toolbar, then table rows. */
function PageBoot({ title }: { title?: string }) {
  return (
    <div className="min-w-0">
      <div className="flex h-12 items-center border-b border-border bg-bg px-6">
        {title ? <h1 className="truncate text-[16px] font-semibold text-fg">{title}</h1> : <Skeleton className="h-4 w-32" />}
      </div>
      <div className="p-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-8 w-28" />
          <Skeleton className="ml-auto h-8 w-24" />
        </div>
        <TableSkeleton />
      </div>
    </div>
  );
}

/** Messages Pro (`MessagesPro`): from lg up the window header, the Fan tabs row and the three panes; below lg the
 *  Creator select over the Fan List. The Fan List's own six skeleton rows (`FanListSkeleton`) either way. */
function MessagesProBoot() {
  return (
    <div className="h-chat flex flex-col overflow-hidden">
      <div className="hidden lg:flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="ml-auto h-8 w-24" />
      </div>
      <div className="hidden lg:flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
        <Skeleton className="h-6 w-28" />
        <Skeleton className="h-6 w-28" />
      </div>
      <div className="lg:hidden shrink-0 px-2 py-1.5 border-b border-border">
        <Skeleton className="h-8 w-full rounded-[6px]" />
      </div>
      <div className="flex-1 min-h-0 lg:flex">
        {/* MP.panes.fanList's width, inlined: reading the token module would put this shell file under the Messages Pro
         *  magic-number guard, which is for the Messages Pro tree. */}
        <div className="lg:w-100 lg:min-w-100 border-r border-border min-h-0 overflow-hidden">
          {/* The Fan List's head (FanList, FanListButtons): its title and icons, Online Fans | Notifications, the
           *  settings and filter buttons with Refresh, the filter chips. */}
          <div className="flex h-[52px] items-center gap-6 border-b border-border px-3">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="ml-auto size-6" />
            <Skeleton className="size-6" />
            <Skeleton className="size-6" />
          </div>
          <div className="flex flex-col gap-3 px-2.5 pt-4 pb-3">
            <div className="flex gap-7">
              <Skeleton className="h-7 flex-1 rounded-[6px]" />
              <Skeleton className="h-7 flex-1 rounded-[6px]" />
            </div>
            <div className="flex items-center gap-2.5">
              <Skeleton className="size-[34px] rounded-[6px]" />
              <Skeleton className="size-[34px] rounded-[6px]" />
              <Skeleton className="ml-auto size-6 rounded-full" />
            </div>
            <div className="flex gap-2.5 overflow-hidden">
              {["w-10", "w-24", "w-[70px]", "w-[70px]", "w-20"].map((w, i) => (
                <Skeleton key={i} className={cn("h-[35px] shrink-0 rounded-full", w)} />
              ))}
            </div>
          </div>
          <FanListSkeleton />
        </div>
        <div className="hidden lg:block flex-1 min-w-0" />
      </div>
    </div>
  );
}
