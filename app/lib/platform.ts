"use client";


import { createContext, useContext, useSyncExternalStore } from "react";

import type { AccountMeta } from "@/lib/relay";

export const CAPABILITIES = [
  "pin_message", "mark_unread", "restrict", "block", "chat_search", "chat_media", "vault_remove", "mass_message",
  "mass_history", "discount", "native_templates", "filter_tips", "filter_priority", "filter_folders", "rich_text",
  "notifications_read", "subscriber_chart", "fan_activity", "native_welcome",
] as const;
export type Capability = (typeof CAPABILITIES)[number];

export const PLATFORMS = [
  { key: "onlyfans", label: "OnlyFans", lacks: [],
    relink: "browserbase", loginDefault: "browser", extensionFormId: "extension-login-form", sessionPrompt: "none", bindsProxy: true,
    profileHost: null,
    logo: [
      { d: "M8 4c-4.416 0-8 3.584-8 8s3.584 8 8 8 8-3.584 8-8-3.584-8-8-8zm0 10.4A2.397 2.397 0 015.6 12c0-1.328 1.072-2.4 2.4-2.4 1.328 0 2.4 1.072 2.4 2.4 0 1.328-1.072 2.4-2.4 2.4z", fill: "#00AEEF" },
      { d: "M16.992 10c2.033.585 4.432 0 4.432 0-.696 3.04-2.904 4.944-6.088 5.176A7.983 7.983 0 018 20l2.4-7.628C12.867 4.532 14.132 4 19.983 4H24c-.672 2.96-2.988 5.221-7.008 6z", fill: "#008CCF" },
    ] },
  { key: "fansly", label: "Fansly", lacks: [
    "pin_message", "mark_unread", "restrict", "block", "chat_search", "chat_media", "vault_remove", "mass_message",
    "discount", "native_templates", "filter_tips", "filter_priority", "filter_folders", "rich_text", "notifications_read",
    "subscriber_chart", "fan_activity", "native_welcome",
  ],
    relink: "fansly", loginDefault: "extension", extensionFormId: "fansly-session-form", sessionPrompt: "Please login Fansly",
    bindsProxy: false, profileHost: "fansly.com",
    logo: [
      { d: "M5.787 2c-1.388.06-2.798.506-3.84 1.468C.744 4.537.176 6.158 0 7.733v.501a5.644 5.644 0 001.571 3.619c2.81 2.896 5.647 5.762 8.483 8.63.533.532 1.026 1.124 1.677 1.517h.484c.717-.251 1.158-.918 1.698-1.415 2.087-2.164 4.266-4.238 6.303-6.45l-6.113-6.234c.69-.703 1.372-1.414 2.074-2.103.57-.574 1.366-.906 2.173-.839 1.64.022 2.998 1.727 2.697 3.364-.177 1.422-1.494 2.195-2.317 3.219l2.066 2c.688-.574 1.332-1.279 1.917-1.96 1.634-1.956 1.716-5.031.223-7.093-.978-1.448-2.631-2.347-4.342-2.489h-.848c-1.266.145-2.514.633-3.456 1.521-2.835 2.809-5.609 5.68-8.446 8.486-.658-.658-1.31-1.32-1.965-1.981-.693-.701-1.061-1.74-.858-2.727.278-1.465 1.763-2.566 3.225-2.32 1.41.153 2.166 1.527 3.182 2.353L11.47 5.36C10.2 3.713 8.486 2.123 6.318 2h-.531zm6.272 9.21c1.38.015 2.705 1.127 2.848 2.556.274 1.774-1.391 3.52-3.15 3.277-1.715-.062-2.968-1.97-2.54-3.617.248-1.086 1.168-1.966 2.25-2.152.196-.045.394-.066.592-.064zm-.031 1.02c-.492 0-.963.199-1.31.552a1.899 1.899 0 00-.543 1.332c0 .5.195.978.542 1.332.348.353.82.551 1.31.551.493 0 .964-.198 1.312-.551a1.899 1.899 0 00.361-2.144.783.783 0 01-.757.087.79.79 0 01-.428-.435.815.815 0 01-.06-.308.814.814 0 01.08-.344 1.827 1.827 0 00-.507-.072z", fill: "#2699F7" },
    ] },
] as const satisfies readonly {
  key: string; label: string; lacks: readonly Capability[];
  relink: string; loginDefault: "browser" | "extension"; extensionFormId: string; sessionPrompt: string; bindsProxy: boolean;
  profileHost: string | null; logo: readonly { d: string; fill: string }[];
}[];

export type PlatformRow = (typeof PLATFORMS)[number];
export type Platform = PlatformRow["key"];

export const UNKNOWN_PLATFORM = "unknown";
export type AccountPlatform = Platform | typeof UNKNOWN_PLATFORM;

export const PLATFORM_NAME = {
  ...Object.fromEntries(PLATFORMS.map((p) => [p.key, p.label])),
  [UNKNOWN_PLATFORM]: "Unknown platform",
} as Record<AccountPlatform, string>;

export const PLATFORM_KEY = "chatterly:platform";
export const DEFAULT_PLATFORM: Platform = "onlyfans";

export const isPlatform = (raw: unknown): raw is Platform => PLATFORMS.some((p) => p.key === raw);

const parse = (raw: string | null): Platform => (isPlatform(raw) ? raw : DEFAULT_PLATFORM);

export function accountPlatform(a: Pick<AccountMeta, "platform">): AccountPlatform {
  const key = typeof a.platform === "string" ? a.platform.trim().toLowerCase() : "";
  if (!key) return DEFAULT_PLATFORM;
  return isPlatform(key) ? key : UNKNOWN_PLATFORM;
}

const ROWS = new Map<AccountPlatform, PlatformRow>(PLATFORMS.map((p) => [p.key, p]));

export function platformRow(p: Platform): PlatformRow;
export function platformRow(p: AccountPlatform | null | undefined): PlatformRow | undefined;
export function platformRow(p: AccountPlatform | null | undefined): PlatformRow | undefined {
  return p == null ? undefined : ROWS.get(p);
}

export const hasSession = (row: PlatformRow): boolean => row.sessionPrompt !== "none";

export function foreignCreator(
  accounts: readonly Pick<AccountMeta, "id" | "platform">[] | undefined,
  id: string | null,
  platform: Platform,
): boolean {
  return !!id && !!accounts?.some((a) => a.id === id && accountPlatform(a) !== platform);
}

export function accountCan(
  accounts: readonly Pick<AccountMeta, "id" | "platform">[], id: string, cap: Capability,
): boolean {
  const a = accounts.find((x) => x.id === id);
  return !a || can(accountPlatform(a), cap);
}

export function can(platform: AccountPlatform | null, cap: Capability): boolean {
  const lacks: readonly Capability[] | undefined = platformRow(platform)?.lacks;
  return !!lacks && !lacks.includes(cap);
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
