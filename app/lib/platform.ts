"use client";


import { createContext, useContext, useSyncExternalStore } from "react";

import type { AccountMeta } from "@/lib/relay";

export const CAPABILITIES = [
  "pin_message", "mark_unread", "restrict", "block", "chat_search", "chat_media", "vault_remove", "mass_message",
  "discount", "native_templates", "filter_tips", "filter_priority", "filter_folders", "rich_text",
] as const;
export type Capability = (typeof CAPABILITIES)[number];

export const PLATFORMS = [
  { key: "onlyfans", label: "OnlyFans", lacks: [] },
  { key: "fansly", label: "Fansly", lacks: [
    "pin_message", "mark_unread", "restrict", "block", "chat_search", "chat_media", "vault_remove", "mass_message",
    "discount", "native_templates", "filter_tips", "filter_priority", "filter_folders", "rich_text",
  ] },
] as const satisfies readonly { key: string; label: string; lacks: readonly Capability[] }[];

export type Platform = (typeof PLATFORMS)[number]["key"];

export const PLATFORM_NAME = Object.fromEntries(PLATFORMS.map((p) => [p.key, p.label])) as Record<Platform, string>;

export const PLATFORM_KEY = "chatterly:platform";
export const DEFAULT_PLATFORM: Platform = "onlyfans";

const isPlatform = (raw: unknown): raw is Platform => PLATFORMS.some((p) => p.key === raw);

const parse = (raw: string | null): Platform => (isPlatform(raw) ? raw : DEFAULT_PLATFORM);

export const accountPlatform = (a: Pick<AccountMeta, "platform">): Platform =>
  isPlatform(a.platform) ? a.platform : DEFAULT_PLATFORM;

export function foreignCreator(
  accounts: readonly Pick<AccountMeta, "id" | "platform">[] | undefined,
  id: string | null,
  platform: Platform,
): boolean {
  return !!id && !!accounts?.some((a) => a.id === id && accountPlatform(a) !== platform);
}

const LACKS = new Map<Platform, ReadonlySet<Capability>>(
  PLATFORMS.map((p): [Platform, ReadonlySet<Capability>] => [p.key, new Set<Capability>(p.lacks)]),
);

export function can(platform: Platform | null, cap: Capability): boolean {
  const lacks = platform === null ? undefined : LACKS.get(platform);
  return !!lacks && !lacks.has(cap);
}

const listeners = new Set<() => void>();
const changeListeners = new Set<(p: Platform) => void>();
let current: Platform | null = null;
let storageHooked = false;

function read(): Platform {
  if (current === null) {
    try {
      current = parse(window.localStorage.getItem(PLATFORM_KEY));
    } catch {
      current = DEFAULT_PLATFORM;
    }
  }
  return current;
}

function apply(p: Platform): void {
  current = p;
  for (const fn of listeners) fn();
  for (const fn of changeListeners) fn(p);
}

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

export const getPlatform = (): Platform => read();

export function setPlatform(p: Platform): void {
  if (read() === p) return;
  try {
    window.localStorage.setItem(PLATFORM_KEY, p);
  } catch { /* private mode: the choice lasts this page */ }
  apply(p);
}

export function onPlatformChange(fn: (p: Platform) => void): () => void {
  hookStorage();
  changeListeners.add(fn);
  return () => {
    changeListeners.delete(fn);
  };
}

/** Server render and hydration read OnlyFans. */
export function usePlatform(): Platform {
  return useSyncExternalStore(subscribe, read, () => DEFAULT_PLATFORM);
}

export const AllPlatformsContext = createContext(false);

export function useFallbackPlatform(): Platform {
  const all = useContext(AllPlatformsContext);
  const sidebar = usePlatform();
  return all ? DEFAULT_PLATFORM : sidebar;
}

export function resetPlatformForTests(): void {
  current = null;
}
