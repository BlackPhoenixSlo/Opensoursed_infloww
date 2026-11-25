"use client";


import { useTranslationAllowed } from "@/lib/appliedSettings";
import { createStoredFlag } from "@/lib/storageSync";

const STORAGE_KEY = "chatterly:translate-en";
const EVENT = "chatterly-translate-mode-change";

export const { read: readTranslateMode, use: useTranslateMode } = createStoredFlag(STORAGE_KEY, EVENT, false);

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
