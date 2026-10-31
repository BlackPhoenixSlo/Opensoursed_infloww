"use client";

/**
 * useTranslateMode — persisted "🌐 translate to English" toggle for the chat
 * thread. Off (default): bubbles render the original text. On: non-English
 * bubbles show the English translation prefixed with a colored "(es)" tag
 * (see useTranslations for the fetch/cache layer).
 *
 * Same custom-event + storage-event pattern as useCompactMedia so the header
 * button (ChatSurface) and every mounted MessageList stay in sync.
 */

import { useTranslationAllowed } from "@/lib/appliedSettings";
import { createStoredFlag } from "@/lib/storageSync";

const STORAGE_KEY = "chatterly:translate-en";
const EVENT = "chatterly-translate-mode-change";

// Default OFF; on is stored as "1", off removes the key. localStorage is
// best-effort persistence only — if its write throws (quota / private mode),
// the flag holds the choice in memory so same-tab readers still agree, and the
// button can never show ON while the thread stays untranslated.
export const { read: readTranslateMode, use: useTranslateMode } = createStoredFlag(STORAGE_KEY, EVENT, false);

/** The effective translate mode in a chat with the Creator `accountId`: the
 *  stored mode AND the Agency's AI translation switch (spec phase-04, stories
 *  56-59). `on` is what the thread and the Composer's switch show; `allowed`
 *  says translation may be sent; `locked` disables the switch with the tooltip
 *  "Turned off by your organization". `setStored` writes the stored mode only,
 *  which the gate never touches, so it returns when the owner turns AI
 *  translation back on.
 *
 *  ASSUMPTION: while the chatter's Applied read has not answered (or failed),
 *  nothing is sent (`allowed` false) and the switch is disabled until the read
 *  answers, so a click never writes a mode the switch cannot show. Rung 4: the
 *  Relay refuses the same chatter on the same Agency context, and an early 403
 *  would pin "No translation available" for the tab's lifetime. Overturned if
 *  a failed read should count as on. */
export function useEffectiveTranslateMode(accountId: string | null): {
  on: boolean;
  allowed: boolean;
  locked: boolean;
  setStored: (next: boolean) => void;
} {
  const [stored, setStored] = useTranslateMode();
  const gate = useTranslationAllowed(accountId);
  const allowed = gate === true;
  return { on: stored && allowed, allowed, locked: !allowed, setStored };
}
