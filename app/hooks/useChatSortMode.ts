"use client";


import { createStoredValue } from "@/lib/storageSync";

export type ChatSortMode = "recent" | "spend" | "spend-unread" | "hybrid";

const STORAGE_KEY = "chatterly:chat-sort-mode";
const EVENT = "chatterly-chat-sort-mode-change";

function isMode(v: unknown): v is ChatSortMode {
  return v === "recent" || v === "spend" || v === "spend-unread" || v === "hybrid";
}

export const { read: readChatSortMode, use: useChatSortMode } = createStoredValue<ChatSortMode>(
  STORAGE_KEY,
  EVENT,
  "recent",
  (raw) => (isMode(raw) ? raw : "recent"),
  (v) => v,
);

// Attention states decay slower so chats needing a reply stay visible longer.
export const HALF_LIFE_IDLE = 1;
export const HALF_LIFE_UNRESPONDED = 2;
export const HALF_LIFE_UNREAD = 3;
export function hybridScore(
  spendCents: number,
  lastIso: string | null | undefined,
  halfLifeHours: number = HALF_LIFE_IDLE,
): number {
  if (!spendCents) return 0;
  if (!lastIso) return spendCents;
  const t = Date.parse(lastIso);
  if (!Number.isFinite(t)) return spendCents;
  const hours = Math.max(0, (Date.now() - t) / 3_600_000);
  return spendCents * Math.pow(0.5, hours / halfLifeHours);
}
