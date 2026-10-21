"use client";

/**
 * fanTyping — "the Fan is typing" from the relay's `chat_typing` SSE push
 * (`{chat_typing: {fan_id}, __account_id}`, service/events.py, at most one per
 * Fan per 3 s). Each push marks the chat typing for TYPING_MS: Infloww's 4 s
 * Typing timeout plus 1 s of slack, so pushes arriving every ~3 s while the
 * Fan types keep it on without flicker. A message from that Fan ends it at
 * once. The OF frame behind the push is not yet seen live, so if it
 * never fires nothing shows.
 */

import { useSyncExternalStore } from "react";

import { eventBus, type EventEnvelope } from "@/lib/events";
import type { FanId } from "@/lib/fanId";

export const TYPING_MS = 5_000;

const until = new Map<string, number>();
const listeners = new Set<() => void>();
let attached = false;

const keyOf = (accountId: string, fanId: FanId | string | number) => `${accountId}:${fanId}`;
const notify = () => { for (const fn of listeners) fn(); };

function setTyping(key: string, on: boolean): void {
  if (on) {
    until.set(key, Date.now() + TYPING_MS);
    // Re-read once it lapses; a newer push only extends the deadline.
    setTimeout(() => {
      if ((until.get(key) ?? 0) <= Date.now()) until.delete(key);
      notify();
    }, TYPING_MS + 50);
  } else if (!until.delete(key)) {
    return;
  }
  notify();
}

/** Applies one SSE envelope: `chat_typing` starts the chat's typing, a
 *  message from the Fan (`api2_chat_message`) ends it. Exported for tests. */
export function applyTypingEvent(e: EventEnvelope, type: string): void {
  const accountId = e.__account_id;
  if (typeof accountId !== "string") return;
  if (type === "chat_typing") {
    const fanId = (e.chat_typing as { fan_id?: unknown } | undefined)?.fan_id;
    if (typeof fanId === "number" || typeof fanId === "string") setTyping(keyOf(accountId, fanId), true);
  } else {
    const fromId = (e.api2_chat_message as { fromUser?: { id?: unknown } } | undefined)?.fromUser?.id;
    if (typeof fromId === "number" || typeof fromId === "string") setTyping(keyOf(accountId, fromId), false);
  }
}

function subscribe(fn: () => void): () => void {
  if (!attached) {
    attached = true;
    eventBus.on("chat_typing", applyTypingEvent);
    eventBus.on("api2_chat_message", applyTypingEvent);
  }
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** The Fan is typing in this Creator's chat right now. */
export function useFanTyping(accountId: string | null | undefined, fanId: FanId | null | undefined): boolean {
  return useSyncExternalStore(
    subscribe,
    () => !!accountId && fanId != null && (until.get(keyOf(accountId, fanId)) ?? 0) > Date.now(),
    () => false,
  );
}
