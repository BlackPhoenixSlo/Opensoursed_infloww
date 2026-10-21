"use client";

/**
 * The platform the app shell is switched to: OnlyFans or Fansly, Infloww's
 * sidebar platform selector (`SelectPlatform`, index.9f50f370.js @11125100).
 *
 * Infloww keeps the choice in a zustand store persisted to localStorage
 * (`useMultiPlatformStore`, `persist(..., {name:"platform"})`, @11121052),
 * OnlyFans by default. Ours persists the same way the app persists the
 * current scope (ScopeContext's `chatterly:scope`): one localStorage key,
 * read after hydration. It is a module store read through
 * useSyncExternalStore, so it needs no provider, and a `storage` event keeps
 * the other windows (a second tab, Messages Pro) on the platform one switched
 * to; each window's PlatformSync then fixes its own scope and page.
 *
 * What the platform drives (code judo: a filter on the existing account
 * scope plus a nav map, not a second app):
 *   - usePlatformAccounts keeps only the platform's accounts, so the creator
 *     switcher, the chat-list fan-out, Messages Pro and the composers follow
 *     it (the notification listeners keep every platform's);
 *   - lib/nav's `sidebarFor` swaps the sidebar to the platform's page set.
 */

import { useSyncExternalStore } from "react";

import type { AccountMeta } from "@/lib/relay";

export type Platform = "onlyfans" | "fansly";

/** The selector's platforms, in Infloww's order. Infloww's mym and Fanvue
 *  (behind `featureInfo.mymEnter` / `fanvueEnter`, @11128150) are not
 *  platforms here: PlatformSwitcher lists them as disabled "Coming soon" rows. */
export const PLATFORMS: readonly Platform[] = ["onlyfans", "fansly"];

export const PLATFORM_NAME: Record<Platform, string> = { onlyfans: "OnlyFans", fansly: "Fansly" };

export const PLATFORM_KEY = "chatterly:platform";
const DEFAULT: Platform = "onlyfans";

const parse = (raw: string | null): Platform => (raw === "fansly" ? "fansly" : DEFAULT);

/** An account's platform; one with no `platform` predates the field and is OnlyFans. */
export const accountPlatform = (a: Pick<AccountMeta, "platform">): Platform =>
  a.platform === "fansly" ? "fansly" : "onlyfans";

const listeners = new Set<() => void>();
const changeListeners = new Set<(p: Platform) => void>();
let current: Platform | null = null;
let storageHooked = false;

function read(): Platform {
  if (current === null) {
    try {
      current = parse(window.localStorage.getItem(PLATFORM_KEY));
    } catch {
      current = DEFAULT;
    }
  }
  return current;
}

function apply(p: Platform): void {
  current = p;
  for (const fn of listeners) fn();
  for (const fn of changeListeners) fn(p);
}

/** One `storage` listener per window: another window (a second tab, Messages
 *  Pro) switched, and this one follows it as a change of its own. */
function hookStorage(): void {
  if (storageHooked || typeof window === "undefined") return;
  storageHooked = true;
  window.addEventListener("storage", (e) => {
    if (e.key !== PLATFORM_KEY) return;
    const p = parse(e.newValue);
    if (p !== read()) apply(p);
  });
}

function subscribe(fn: () => void): () => void {
  hookStorage();
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** The current platform, outside React. */
export const getPlatform = (): Platform => read();

export function setPlatform(p: Platform): void {
  if (read() === p) return;
  try {
    window.localStorage.setItem(PLATFORM_KEY, p);
  } catch { /* private mode: the choice lasts this page */ }
  apply(p);
}

/**
 * Hears every switch, in this window (the selector, a route) or another
 * (`storage`), but not the first read after load. PlatformSync reconciles the
 * window's scope and page on it.
 */
export function onPlatformChange(fn: (p: Platform) => void): () => void {
  hookStorage();
  changeListeners.add(fn);
  return () => {
    changeListeners.delete(fn);
  };
}

/** The current platform; the server render and hydration read OnlyFans. */
export function usePlatform(): Platform {
  return useSyncExternalStore(subscribe, read, () => DEFAULT);
}

/** Test seam: forget the cached value so the next read goes to localStorage. */
export function resetPlatformForTests(): void {
  current = null;
}
