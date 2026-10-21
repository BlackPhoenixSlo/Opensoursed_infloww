"use client";

import { useSyncExternalStore } from "react";

declare global {
  interface Window {
    /** The desktop app's bridge (desktop/preload.js), frozen before any page script runs; absent on the web. The
     *  preload always sets all three; `platform` and `version` are optional so a test can fake just `isDesktop`. */
    fasttShell?: {
      isDesktop: boolean;
      platform?: string;
      version?: string;
      /** Native OS notification (lib/osNotify); resolves true when it was shown. */
      notify?: (n: { id: string; title: string; body: string; href: string }) => Promise<boolean>;
    };
  }
}

/** The desktop app's preload (desktop/preload.js) sets it before any page script and never changes it. */
const subscribe = () => () => {};

/** True inside the Inflowwww desktop app (`window.fasttShell.isDesktop`). The server renders as if inside
 *  the app, so a web-only link such as /download is left out of the first paint and appears after hydration
 *  on the web: never a flash of it in the app. A client-only render (a modal opened later) is right at once. */
export function useInDesktopApp(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.fasttShell?.isDesktop === true,
    () => true,
  );
}
