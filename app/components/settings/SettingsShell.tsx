"use client";


import { usePathname, useRouter } from "next/navigation";
import { X } from "lucide-react";

import SettingsNav from "@/components/settings/SettingsNav";
import { DeniedPagePanel } from "@/components/shell/DeniedPage";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { useInDesktopApp } from "@/hooks/useInDesktopApp";
import { SETTINGS_TABS } from "@/lib/nav";
import { DESKTOP_TITLE, DESKTOP_URL } from "@/lib/brand";

export default function SettingsShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const chatterOnly = useIsChatterOnly();
  const inApp = useInDesktopApp();
  const ownerOnly = chatterOnly && SETTINGS_TABS.some((t) => t.chatterHidden && t.href === pathname);
  // A deep link opened in a new tab has no history to go back to.
  const close = () => (window.history.length > 1 ? router.back() : router.push("/"));

  return (
    <div className="bg-[var(--if-bg)] min-h-[calc(100dvh-var(--shell-top,3.5rem))]">
      <header
        data-settings="header"
        className="h-[var(--if-header-h)] px-3 sm:px-6 md:px-[var(--if-panel-pad)] flex items-center gap-3 border-b border-[var(--if-line)]"
      >
        <h1 className="text-[length:var(--if-fs-lg)] font-[var(--if-fw-title)] text-[var(--if-fg)]">Settings</h1>
        <div className="ml-auto flex items-center gap-3">
          {!inApp && (
            <a
              href={DESKTOP_URL}
              title={DESKTOP_TITLE}
              className="hidden sm:flex items-center gap-1.5 h-8 px-3 rounded border border-[var(--if-line)] text-[length:var(--if-fs)] text-[var(--if-fg-2)] hover:text-[var(--if-fg)] whitespace-nowrap"
            >
              <span aria-hidden="true">&#8595;</span>
              Desktop app
            </a>
          )}
          <button
            type="button"
            aria-label="Close settings"
            title="Close settings"
            onClick={close}
            className="grid place-items-center text-[var(--if-fg-3)] hover:text-[var(--if-fg)]"
          >
            <X aria-hidden className="w-4 h-4" />
          </button>
        </div>
      </header>
      <div
        data-settings="tab-area"
        className="@container flex flex-col md:flex-row gap-5 md:gap-0 p-3 sm:p-6 md:p-0 md:h-[calc(100dvh-var(--shell-top,3.5rem)-var(--if-header-h))]"
      >
        <SettingsNav />
        <div className="flex-1 min-w-0 md:overflow-y-auto md:p-[var(--if-panel-pad)] md:has-[>[data-settings=panel]]:p-0">
          {ownerOnly ? <DeniedPagePanel /> : children}
        </div>
      </div>
    </div>
  );
}
