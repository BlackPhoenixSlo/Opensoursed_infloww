"use client";

import { useSyncExternalStore } from "react";

declare global {
  interface Window {
    fasttShell?: {
      isDesktop: boolean;
      platform?: string;
      version?: string;
      notify?: (n: { id: string; title: string; body: string; href: string }) => Promise<boolean>;
      openGoLive?: (creatorId: string) => Promise<{ ok: boolean; signIn?: boolean; error?: string }>;
    };
  }
}

const subscribe = () => () => {};

export function useInDesktopApp(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.fasttShell?.isDesktop === true,
    // Server renders as in-app: web-only links appear after hydration on the web, never flash inside the app.
    () => true,
  );
}
