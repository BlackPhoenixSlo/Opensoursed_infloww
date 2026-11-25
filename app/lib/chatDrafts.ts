"use client";


import { useCallback, useEffect, useState, useSyncExternalStore, type Dispatch, type SetStateAction } from "react";

import type { FanId } from "@/lib/fanId";
import { subscribeToStorage } from "@/lib/storageSync";

const EVENT = "mp-chat-draft-change";
const subscribe = subscribeToStorage(EVENT);

export const chatDraftKey = (accountId: string, fanId: FanId) => `mp:draft:${accountId}:${fanId}`;

export function readChatDraft(accountId: string | null, fanId: FanId | null): string {
  if (!accountId || fanId == null || typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(chatDraftKey(accountId, fanId)) ?? "";
  } catch {
    return "";
  }
}

function writeChatDraft(accountId: string, fanId: FanId, text: string): void {
  const key = chatDraftKey(accountId, fanId);
  if (readChatDraft(accountId, fanId) === (text.trim() ? text : "")) return;
  try {
    if (text.trim()) window.sessionStorage.setItem(key, text);
    else window.sessionStorage.removeItem(key);
  } catch {
    return;
  }
  window.dispatchEvent(new Event(EVENT));
}

export interface ChatRich { html: string; plain: string }
export const chatRichKey = (accountId: string, fanId: FanId) => `mp:draft-rich:${accountId}:${fanId}`;

export function readChatRich(accountId: string | null, fanId: FanId | null): ChatRich | null {
  if (!accountId || fanId == null || typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(chatRichKey(accountId, fanId));
    const r = raw ? (JSON.parse(raw) as ChatRich) : null;
    if (!r || typeof r.html !== "string" || typeof r.plain !== "string") return null;
    return readChatDraft(accountId, fanId).trim() === r.plain.trim() ? r : null;
  } catch {
    return null;
  }
}

export function writeChatRich(accountId: string | null, fanId: FanId | null, rich: ChatRich | null): void {
  if (!accountId || fanId == null || typeof window === "undefined") return;
  try {
    if (rich) window.sessionStorage.setItem(chatRichKey(accountId, fanId), JSON.stringify(rich));
    else window.sessionStorage.removeItem(chatRichKey(accountId, fanId));
  } catch {
    return;
  }
}

export function useChatDraft(accountId: string | null, fanId: FanId | null): [string, Dispatch<SetStateAction<string>>] {
  const [text, setText] = useState(() => readChatDraft(accountId, fanId));
  useEffect(() => {
    if (accountId && fanId != null) writeChatDraft(accountId, fanId, text);
  }, [accountId, fanId, text]);
  const set = useCallback((next: SetStateAction<string>) => {
    if (typeof next === "string" && accountId && fanId != null) writeChatDraft(accountId, fanId, next);
    setText(next);
  }, [accountId, fanId]);
  return [text, set];
}

export function useChatDraftText(accountId: string | null, fanId: FanId | null): string {
  return useSyncExternalStore(subscribe, () => readChatDraft(accountId, fanId), () => "");
}
