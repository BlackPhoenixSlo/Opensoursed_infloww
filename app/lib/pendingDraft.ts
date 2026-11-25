import { useEffect, useRef } from "react";

import { persistJSON, readJSON } from "@/lib/persist";

export interface DraftEntry<T> {
  draft: T;
  base: T;
  at: number;
}

export const DRAFT_DEBOUNCE_MS = 300;

export function stableJSON(v: unknown): string {
  const norm = (x: unknown): unknown => {
    if (Array.isArray(x)) return x.map(norm);
    if (x && typeof x === "object") {
      return Object.fromEntries(
        Object.keys(x as object).sort().map((k) => [k, norm((x as Record<string, unknown>)[k])]),
      );
    }
    return x;
  };
  return JSON.stringify(norm(v));
}

export function stashDraft<T>(key: string, entry: DraftEntry<T>): boolean {
  return persistJSON(key, entry);
}

export function readDraft<T>(key: string): DraftEntry<T> | null {
  const v = readJSON<DraftEntry<T>>(key);
  return v && typeof v === "object" && "draft" in v && "base" in v ? v : null;
}

export function clearDraft<T>(key: string, ifEquals?: T): boolean {
  if (typeof window === "undefined") return false;
  if (ifEquals !== undefined) {
    const cur = readDraft<T>(key);
    if (cur && stableJSON(cur.draft) !== stableJSON(ifEquals)) return false;
  }
  try {
    window.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function usePendingDraft<T>(key: string | null, value: { draft: T; base: T } | null): void {
  const pending = useRef<{ key: string; entry: DraftEntry<T> } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const flush = useRef(() => {
    clearTimeout(timer.current);
    timer.current = undefined;
    const p = pending.current;
    pending.current = null;
    if (p) stashDraft(p.key, p.entry);
  }).current;

  useEffect(() => {
    const onVisibility = () => { if (document.visibilityState === "hidden") flush(); };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", flush);
    window.addEventListener("beforeunload", flush);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", flush);
      window.removeEventListener("beforeunload", flush);
      flush();
    };
  }, [flush]);

  const latest = useRef(value);
  useEffect(() => { latest.current = value; });
  const json = value === null ? null : JSON.stringify(value);
  useEffect(() => {
    if (pending.current && pending.current.key !== key) flush();
    if (key === null) return;
    clearTimeout(timer.current);
    const v = latest.current;
    if (json === null || v === null) {
      pending.current = null;
      clearDraft(key);
      return;
    }
    pending.current = { key, entry: { draft: v.draft, base: v.base, at: Date.now() } };
    timer.current = setTimeout(flush, DRAFT_DEBOUNCE_MS);
  }, [key, json, flush]);
}
