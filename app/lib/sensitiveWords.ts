"use client";


import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { relay } from "@/lib/relay";

export const SENSITIVE_WORDS_KEY = ["sensitive-words"] as const;
export const SENSITIVE_WORD_MAX = 32;
export const SENSITIVE_WORD_ROWS_MAX = 20;
export const SENSITIVE_HIT_LEAD = "Input contains prohibited language: ";
export const SENSITIVE_BLOCK_MESSAGE = "Please check the contents of the messages";

const EMOJI_SRC =
  "(?:\\p{Emoji_Modifier_Base}\\p{Emoji_Modifier}|\\p{Emoji_Presentation}|\\p{Emoji}\\uFE0F)" +
  "(?:\\u200D(?:\\p{Emoji_Modifier_Base}\\p{Emoji_Modifier}|\\p{Emoji_Presentation}|\\p{Emoji}\\uFE0F))*";
const emojiRe = () => new RegExp(EMOJI_SRC, "gu");
const BOUNDARY = "[\\s.,!?()\\-[\\]{}'‘’\"@#$%^&*_+=|:;<>/~`\\\\\\p{Emoji_Presentation}]";
const LB = `(?:^|(?<=${BOUNDARY}))`;
const LA = `(?=$|${BOUNDARY})`;

export interface CompiledWord {
  original: string;
  pattern: RegExp;
  hasEmoji: boolean;
}

const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const containsEmoji = (s: string) => emojiRe().test(s);
const textPattern = (s: string) => s.trim().split(/\s+/).filter(Boolean).map(escapeRegex).join("\\s+");

function buildPattern(word: string): RegExp {
  const w = word.trim();
  if (!containsEmoji(w)) return new RegExp(`${LB}${textPattern(w)}${LA}`, "iu");
  const parts: string[] = [];
  const re = emojiRe();
  let last = 0;
  for (let m = re.exec(w); m !== null; m = re.exec(w)) {
    const before = w.slice(last, m.index);
    if (before) {
      parts.push(textPattern(before));
      const trail = before.match(/\s+$/)?.[0];
      if (trail) parts.push(` {${trail.length}}`);
    }
    parts.push(escapeRegex(m[0]));
    last = re.lastIndex;
    const lead = w.slice(last).match(/^\s+/)?.[0];
    if (lead) parts.push(` {${lead.length}}`);
  }
  const rest = w.slice(last);
  if (rest) parts.push(textPattern(rest));
  return new RegExp(`${LB}${parts.join("")}${LA}`, "iu");
}

export function compileWords(words: readonly string[]): CompiledWord[] {
  return words
    .map((w) => w.trim())
    .filter(Boolean)
    .map((original) => ({ original, pattern: buildPattern(original), hasEmoji: containsEmoji(original) }));
}

export function matchSensitiveWords(text: string, compiled: readonly CompiledWord[]): string[] {
  if (!text || compiled.length === 0) return [];
  const noEmoji = text.replace(emojiRe(), " ");
  const hits = compiled.filter(({ pattern, hasEmoji }) => pattern.test(hasEmoji ? text : noEmoji));
  return [...new Set(hits.map((h) => h.original))];
}

export const SPECIAL_TAB = "Special symbol";
export const LETTER_TABS = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ", SPECIAL_TAB] as const;
export function tabOf(word: string): string {
  const c = word.trim().charAt(0).toUpperCase();
  return c >= "A" && c <= "Z" ? c : SPECIAL_TAB;
}

export function useSensitiveWords(accountId?: string | null) {
  return useQuery({
    queryKey: [...SENSITIVE_WORDS_KEY, accountId ?? null],
    queryFn: () =>
      relay.get<{ words: string[] }>(
        accountId ? `/admin/sensitive-words?account_id=${encodeURIComponent(accountId)}` : "/admin/sensitive-words",
      ),
    staleTime: 60_000,
  });
}

export function useSensitiveHits(text: string, accountId?: string | null): string[] {
  const words = useSensitiveWords(accountId).data?.words;
  const compiled = useMemo(() => compileWords(words ?? []), [words]);
  return useMemo(() => matchSensitiveWords(text, compiled), [text, compiled]);
}
