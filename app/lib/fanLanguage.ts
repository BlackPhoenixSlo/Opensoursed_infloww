"use client";

/**
 * fanLanguage — the language a chatter writes to one Fan in (Infloww's
 * per-Fan translation language, 04 M16), kept per Creator and Fan in this
 * browser's localStorage (`mp:fan-lang:<accountId>:<fanId>`). The composer's
 * outbound translation translates into it through /admin/translate's `target`.
 */

import { useCallback, useSyncExternalStore } from "react";

import type { FanId } from "@/lib/fanId";
import { subscribeToStorage } from "@/lib/storageSync";

/** The targets offered, as the bare ISO 639-1 codes /admin/translate keeps
 *  (it drops a region suffix, so there is one Chinese). */
export const LANGUAGES: { code: string; name: string }[] = [
  { code: "ar", name: "Arabic" }, { code: "bg", name: "Bulgarian" }, { code: "zh", name: "Chinese" },
  { code: "hr", name: "Croatian" }, { code: "cs", name: "Czech" },
  { code: "da", name: "Danish" }, { code: "nl", name: "Dutch" }, { code: "en", name: "English" },
  { code: "fi", name: "Finnish" }, { code: "fr", name: "French" }, { code: "de", name: "German" },
  { code: "el", name: "Greek" }, { code: "he", name: "Hebrew" }, { code: "hi", name: "Hindi" },
  { code: "hu", name: "Hungarian" }, { code: "id", name: "Indonesian" }, { code: "it", name: "Italian" },
  { code: "ja", name: "Japanese" }, { code: "ko", name: "Korean" }, { code: "ms", name: "Malay" },
  { code: "no", name: "Norwegian" }, { code: "pl", name: "Polish" }, { code: "pt", name: "Portuguese" },
  { code: "ro", name: "Romanian" }, { code: "ru", name: "Russian" }, { code: "sr", name: "Serbian" },
  { code: "sk", name: "Slovak" }, { code: "sl", name: "Slovenian" }, { code: "es", name: "Spanish" },
  { code: "sv", name: "Swedish" }, { code: "tl", name: "Tagalog" }, { code: "th", name: "Thai" },
  { code: "tr", name: "Turkish" }, { code: "uk", name: "Ukrainian" }, { code: "vi", name: "Vietnamese" },
];

const EVENT = "mp-fan-language-change";
const subscribe = subscribeToStorage(EVENT);

export const fanLanguageKey = (accountId: string, fanId: FanId) => `mp:fan-lang:${accountId}:${fanId}`;

function read(accountId: string | null, fanId: FanId | null): string | null {
  if (!accountId || fanId == null || typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(fanLanguageKey(accountId, fanId));
  } catch {
    return null;
  }
}

/** The Fan's language code (null: none chosen) and its setter (null clears). */
export function useFanLanguage(
  accountId: string | null, fanId: FanId | null,
): [string | null, (code: string | null) => void] {
  const code = useSyncExternalStore(subscribe, () => read(accountId, fanId), () => null);
  const set = useCallback((next: string | null) => {
    if (!accountId || fanId == null) return;
    try {
      if (next) window.localStorage.setItem(fanLanguageKey(accountId, fanId), next);
      else window.localStorage.removeItem(fanLanguageKey(accountId, fanId));
    } catch {
      return;
    }
    window.dispatchEvent(new Event(EVENT));
  }, [accountId, fanId]);
  return [code, set];
}
