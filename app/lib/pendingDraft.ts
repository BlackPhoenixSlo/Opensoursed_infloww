/**
 * A form's unsaved draft kept in localStorage until the server acks it, so a
 * tab closed (or reloaded) mid-edit or mid-save gets it back on reopen.
 *
 *   • `stashDraft(key, {draft, base, at})`: `base` is what the server held when
 *     the draft was made — a reopen that finds the server moved off it warns
 *     instead of silently writing over the other change.
 *   • `clearDraft(key, ifEquals)`: the ack. Only drops the stash when it still
 *     holds what that save wrote — an edit typed during the PUT stays.
 *   • `usePendingDraft(key, value)`: writes the dirty draft (debounced) and
 *     flushes it at once when the page hides, unloads, the key changes or the
 *     form unmounts; `value` null = nothing dirty → the stash goes. `key` null =
 *     not loaded yet (a draft there is the reopen's to read) → nothing touched.
 *
 * Keys live under `chatterly:` so logout's sweep (UserContext) drops them.
 */

import { useEffect, useRef } from "react";

import { persistJSON, readJSON } from "@/lib/persist";

export interface DraftEntry<T> {
  draft: T;
  base: T;
  /** ms when written. */
  at: number;
}

export const DRAFT_DEBOUNCE_MS = 300;

/** JSON with object keys sorted (array order kept) — equal values, equal strings. */
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

/** False when the write didn't land (SSR, quota) — the draft then lives in memory only. */
export function stashDraft<T>(key: string, entry: DraftEntry<T>): boolean {
  return persistJSON(key, entry);
}

export function readDraft<T>(key: string): DraftEntry<T> | null {
  const v = readJSON<DraftEntry<T>>(key);
  return v && typeof v === "object" && "draft" in v && "base" in v ? v : null;
}

/** Drop the stash — with `ifEquals`, only if its draft is that value (key order ignored).
 *  True when nothing is stored under `key` afterwards. */
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
      flush(); // unmount: a dirty draft outlives the form
    };
  }, [flush]);

  // The write runs when the value's content changes, not its identity (a
  // fresh object every render); it reads the value itself from `latest`,
  // synced by the effect before it (effects run in order).
  const latest = useRef(value);
  useEffect(() => { latest.current = value; });
  const json = value === null ? null : JSON.stringify(value);
  useEffect(() => {
    if (pending.current && pending.current.key !== key) flush(); // the old key's draft lands first
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
