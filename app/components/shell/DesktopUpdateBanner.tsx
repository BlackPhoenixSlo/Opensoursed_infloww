"use client";

/**
 * "Desktop update available": inside the desktop app only, when the shell's version (`window.fasttShell.version`,
 * desktop/preload.js) is older than LATEST_DESKTOP_VERSION. It links to /download (in a new window: the desktop
 * opens a same-origin one in the app, and the page's download links go to the OS browser). No network call; the
 * close is remembered per latest version, so the next release shows it again. The server render has no shell, so
 * it shows after hydration.
 */

import { useSyncExternalStore } from "react";
import { X } from "lucide-react";

import { isOlderVersion, LATEST_DESKTOP_VERSION } from "@/lib/desktopVersion";
import { subscribeToStorage } from "@/lib/storageSync";

const CLOSED_KEY = "chatterly:desktop-update-closed";
const CLOSED_EVENT = "desktop-update-banner-closed";
const subscribeClosed = subscribeToStorage(CLOSED_EVENT);

function shouldShow(): boolean {
  if (!isOlderVersion(window.fasttShell?.version, LATEST_DESKTOP_VERSION)) return false;
  try {
    return localStorage.getItem(CLOSED_KEY) !== LATEST_DESKTOP_VERSION;
  } catch {
    return true;
  }
}

export function DesktopUpdateBanner() {
  const show = useSyncExternalStore(subscribeClosed, shouldShow, () => false);
  if (!show) return null;
  const close = () => {
    try { localStorage.setItem(CLOSED_KEY, LATEST_DESKTOP_VERSION); } catch {}
    window.dispatchEvent(new Event(CLOSED_EVENT));
  };
  return (
    <div
      role="status"
      className="fixed bottom-3 right-3 z-[60] flex items-center gap-3 rounded-lg border border-border bg-bg-elev-1 px-3 py-2 text-sm text-fg shadow-lg"
    >
      <span>Desktop update available (v{LATEST_DESKTOP_VERSION})</span>
      <a href="/download" target="_blank" rel="noopener" className="text-accent underline">
        Download
      </a>
      <button
        type="button"
        onClick={close}
        aria-label="Close update banner"
        className="w-6 h-6 grid place-items-center rounded text-fg-dim hover:text-fg hover:bg-bg-elev-2"
      >
        <X aria-hidden className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
