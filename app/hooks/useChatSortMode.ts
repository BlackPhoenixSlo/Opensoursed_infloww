"use client";

/**
 * useChatSortMode — persisted "how should the chat sidebar be ordered?"
 * toggle.
 *
 * Four states:
 *   • "recent"        — server order (last activity desc), shown as
 *                       Infloww's "Newest first" (default)
 *   • "spend"         — lifetime spend desc; rows with no spend drop to
 *                       bottom, ordered by last activity within ties
 *   • "spend-unread"  — three tiers (unread → owe-reply → idle), spend
 *                       desc within each
 *   • "hybrid"        — spend with tiered exponential decay (1h/2h/3h
 *                       half-life based on attention state); below a
 *                       $3 effective threshold, unread tiebreak kicks
 *                       in so fresh conversations don't drown
 *
 * Same custom-event + storage-event pattern as useBlurMode so sibling
 * tabs / windows stay in sync. Every choice is stored, the default's too, so
 * a later change of default never overrides a choice
 * (docs/spec/phase-02-fan-list-pane.md, Interfaces).
 */

import { useEffect, useState } from "react";

export type ChatSortMode = "recent" | "spend" | "spend-unread" | "hybrid";

const STORAGE_KEY = "chatterly:chat-sort-mode";
const EVENT = "chatterly-chat-sort-mode-change";

function isMode(v: unknown): v is ChatSortMode {
  return v === "recent" || v === "spend" || v === "spend-unread" || v === "hybrid";
}

export function readChatSortMode(): ChatSortMode {
  if (typeof window === "undefined") return "recent";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return isMode(raw) ? raw : "recent";
}

export function useChatSortMode(): [ChatSortMode, (next: ChatSortMode) => void] {
  const [val, setVal] = useState<ChatSortMode>(() => readChatSortMode());

  useEffect(() => {
    const onChange = () => setVal(readChatSortMode());
    window.addEventListener(EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);

  function update(next: ChatSortMode) {
    setVal(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
      window.dispatchEvent(new Event(EVENT));
    } catch { /* quota — silent */ }
  }

  return [val, update];
}

/** Hybrid score: spend dollars weighted by an exponential decay against
 *  hours since the fan's last interaction. Half-life is tiered by chat
 *  state — chats that need our attention decay slower so they stay
 *  visible longer:
 *    • read + we-sent-last (idle):       1h half-life
 *    • read + fan-sent-last (owe reply): 2h half-life
 *    • unread:                           3h half-life
 *  Callers pass the appropriate half-life per row. */
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
