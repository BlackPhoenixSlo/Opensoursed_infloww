"use client";

/**
 * Infloww's Settings frame (docs/spec/settings-tabs/phase-00-shell-tokens-blob.md):
 * the 48px Settings header ("Settings", our "Desktop app" link, also on the About tab, and a ✕ that leaves
 * Settings, over a full-width rule) over the
 * Tab area: a size container that fills the viewport under the app's top bar
 * (md and up), in which the Tab list and the Panel each scroll on their own. Reads Infloww's `--if-*` tokens
 * (globals.css, ADR-0009), which is why the header lives here and not in the
 * server layout. A tab hidden from a Chatter (`chatterHidden`), opened by URL
 * in a Chatter-only session, shows the denied-page panel instead of its Panel
 * (the Relay refuses its routes too).
 */

import { usePathname, useRouter } from "next/navigation";
import { X } from "lucide-react";

import SettingsNav from "@/components/settings/SettingsNav";
import { DeniedPagePanel } from "@/components/shell/DeniedPage";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { useInDesktopApp } from "@/hooks/useInDesktopApp";
import { SETTINGS_TABS } from "@/lib/nav";

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
        className="h-[var(--if-header-h)] px-[var(--if-panel-pad)] flex items-center gap-3 border-b border-[var(--if-line)]"
      >
        <h1 className="text-[length:var(--if-fs-lg)] font-[var(--if-fw-title)] text-[var(--if-fg)]">Settings</h1>
        <div className="ml-auto flex items-center gap-3">
          {/* Get the desktop app. A plain <a>, not next/link: /download is a static file in public/, outside the
              router. Hidden below sm and inside the desktop app. */}
          {!inApp && (
            <a
              href="/download"
              title="Get the Inflowwww desktop app for Mac and Windows"
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
        {/* A Settings tab renders its own Panel (header + scrolling body, SettingsPanel.tsx), so a
            slot holding one is a bare frame; a Legacy tab, or a 404, keeps the padded slot. */}
        <div className="flex-1 min-w-0 md:overflow-y-auto md:p-[var(--if-panel-pad)] md:has-[>[data-settings=panel]]:p-0">
          {ownerOnly ? <DeniedPagePanel /> : children}
        </div>
      </div>
    </div>
  );
}
