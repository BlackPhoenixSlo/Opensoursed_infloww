"use client";


import { useSyncExternalStore } from "react";

import { eventBus, type EventEnvelope } from "@/lib/events";
import type { FanId } from "@/lib/fanId";

// Infloww's 4 s typing timeout + 1 s slack, so ~3 s relay pushes keep it on without flicker; the OF frame behind the push is not seen live yet
export const TYPING_MS = 5_000;

const until = new Map<string, number>();
const listeners = new Set<() => void>();
let attached = false;

const keyOf = (accountId: string, fanId: FanId | string | number) => `${accountId}:${fanId}`;
const notify = () => { for (const fn of listeners) fn(); };

function setTyping(key: string, on: boolean): void {
  if (on) {
    until.set(key, Date.now() + TYPING_MS);
    setTimeout(() => {
      if ((until.get(key) ?? 0) <= Date.now()) until.delete(key);
      notify();
    }, TYPING_MS + 50);
  } else if (!until.delete(key)) {
    return;
  }
  notify();
}

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

export function useFanTyping(accountId: string | null | undefined, fanId: FanId | null | undefined): boolean {
  return useSyncExternalStore(
    subscribe,
    () => !!accountId && fanId != null && (until.get(keyOf(accountId, fanId)) ?? 0) > Date.now(),
    () => false,
  );
}
