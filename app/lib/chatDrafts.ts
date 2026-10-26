"use client";

/**
 * chatDrafts — Messages Pro's per-chat composer draft: the unsent text, kept
 * per Creator and Fan in sessionStorage (`mp:draft:<accountId>:<fanId>`, as
 * the OF mirror keeps its Chat draft, `ofMirrorChat.ts`), so switching Fans
 * keeps it and the Fan List can mark the row "[Draft]" (Infloww's Fan List
 * preview, MP2 `message-HF80yTBL.js`). Only the text: attachments, price and
 * schedule still go with the chat. Blank text removes the entry, so sending
 * (which empties the composer) clears it.
 */

import { useCallback, useEffect, useState, useSyncExternalStore, type Dispatch, type SetStateAction } from "react";

import type { FanId } from "@/lib/fanId";
import { subscribeToStorage } from "@/lib/storageSync";

const EVENT = "mp-chat-draft-change";
const subscribe = subscribeToStorage(EVENT);

export const chatDraftKey = (accountId: string, fanId: FanId) => `mp:draft:${accountId}:${fanId}`;

/** The stored draft, or "" (none, no storage, or no chat). */
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
    return; // storage full or blocked: the draft lives only in the composer
  }
  window.dispatchEvent(new Event(EVENT));
}

/** The composer's text state, restored from and saved to the chat's draft.
 *  Without a chat (a mass composer) it is plain state. The Composer remounts
 *  per chat (MessagesPro keys ChatSurface by Creator and Fan), so the draft
 *  is read once, at mount. A plain value is saved as it is set: a send that
 *  empties the draft can unmount the composer in the same render (a queue
 *  key that sends and moves on), before an effect would run. */
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

/** The chat's stored draft text ("" for none), live across the window. */
export function useChatDraftText(accountId: string | null, fanId: FanId | null): string {
  return useSyncExternalStore(subscribe, () => readChatDraft(accountId, fanId), () => "");
}
