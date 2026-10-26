"use client";

/**
 * About Inflowwww (docs/spec/settings-tabs/phase-05-billing-balance-about.md): an 88x88 tile drawn from
 * the "Inflowwww" wordmark (no image asset), "Version {version}" from the app's package.json as the
 * Sidebar shows it, then a 760px desktop-app box where Infloww has its beta box, and the licence link, centred
 * in the Panel. No beta box, no build hash; the Panel makes no request and stores nothing (ADR-0008).
 */

import { IF_BTN, SettingsPanel } from "@/components/settings/SettingsPanel";
import { useInDesktopApp } from "@/hooks/useInDesktopApp";
import { REPO_URL } from "@/lib/repoUrl";
import { version } from "@/package.json";
import { cn } from "@/lib/utils";
import { BRAND_LOGO, BRAND_NAME } from "@/lib/brand";

const LINK = "text-[length:var(--if-fs)] text-[var(--if-accent)] hover:underline underline-offset-2";

export default function AboutTab() {
  const inApp = useInDesktopApp();
  return (
    <SettingsPanel title="About">
      <div className="grid min-h-full place-items-center py-10">
        <div className="flex w-full flex-col items-center text-center">
          {BRAND_LOGO ? (
            // eslint-disable-next-line @next/next/no-img-element -- a static PNG from public/
            <img src={`${BRAND_LOGO}-512.png`} alt={BRAND_NAME} className="mb-6 size-[88px] rounded-full" />
          ) : (
            <div
              role="img"
              aria-label={BRAND_NAME}
              className="mb-6 grid w-[88px] h-[88px] place-items-center rounded-[16px] bg-[var(--if-list-bg)] text-[16px] font-semibold leading-tight tracking-tight text-[var(--if-fg)]"
            >
              <span aria-hidden>{BRAND_NAME}</span>
            </div>
          )}
          <p className="mb-8 text-[length:var(--if-fs)] text-[var(--if-fg)]">Version {version}</p>
          {/* Where Infloww's `._join-beta-wrap` sits: 760px, 16px padding, an L1 border, radius 4. Not in the app. */}
          {!inApp && (
            <div className="mb-4 flex w-[760px] max-w-full items-center justify-between gap-4 rounded border border-[var(--if-line)] p-4 text-left">
              <div>
                <p className="text-[length:var(--if-fs-lg)] font-medium text-[var(--if-fg)]">Get the desktop app</p>
                <p className="text-[length:var(--if-fs)] text-[var(--if-fg-2)]">{BRAND_NAME} for Mac and Windows</p>
              </div>
              {/* A plain <a>: /download is a static file outside the router. */}
              <a href="/download" className={cn(IF_BTN, "inline-flex shrink-0 items-center")}>
                Download
              </a>
            </div>
          )}
          <a href={`${REPO_URL}/blob/main/LICENSE`} target="_blank" rel="noopener noreferrer" className={LINK}>
            MIT License
          </a>
        </div>
      </div>
    </SettingsPanel>
  );
}
