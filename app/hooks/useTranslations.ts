"use client";


import { useEffect, useState } from "react";

import type { FanId } from "@/lib/fanId";
import { relay } from "@/lib/relay";

export interface BubbleTranslation {
  text: string;
  lang: string;
}

const CHUNK = 40;
export const FAILED_RETRY_MS = 60_000;

const caches = new Map<string, Map<string, BubbleTranslation | null>>();
const failedAt = new Map<string, number>();
const inFlight = new Set<string>();

function cacheFor(scope: string) {
  let c = caches.get(scope);
  if (!c) caches.set(scope, (c = new Map()));
  return c;
}

export function resetTranslationsForTests() {
  caches.clear();
  failedAt.clear();
  inFlight.clear();
}

export function useTranslations(
  texts: string[],
  enabled: boolean,
  accountId: string | null,
  hint: string | null = null,
  fanId: FanId | null = null,
): Map<string, BubbleTranslation | null> {
  const [, bump] = useState(0);
  const scope = hint ? JSON.stringify([hint]) : JSON.stringify([accountId, fanId == null ? null : String(fanId)]);
  const cache = cacheFor(scope);

  useEffect(() => {
    if (!enabled) return;
    const tag = (t: string) => `${scope}\u0000${t}`;
    const now = Date.now();
    const missing = Array.from(new Set(texts)).filter(
      (t) => t && !inFlight.has(tag(t))
        && (!cache.has(t) || (cache.get(t) === null && now - (failedAt.get(tag(t)) ?? 0) >= FAILED_RETRY_MS)),
    );
    if (!missing.length) return;
    let cancelled = false;
    (async () => {
      for (let i = 0; i < missing.length; i += CHUNK) {
        const chunk = missing.slice(i, i + CHUNK);
        // Acquire per chunk: acquiring all of `missing` upfront leaked unfetched chunks when cancelled mid-run, blocking the tail of long threads.
        chunk.forEach((t) => inFlight.add(tag(t)));
        let results: Array<BubbleTranslation | null> = [];
        try {
          const resp = await relay.post<{ results: Array<BubbleTranslation | null> }>(
            "/admin/translate",
            hint ? { texts: chunk, target: "en", hint } : { texts: chunk, target: "en" },
            { accountId },
          );
          results = resp.results ?? [];
        } catch {
          results = [];
        } finally {
          chunk.forEach((t) => inFlight.delete(tag(t)));
        }
        const at = Date.now();
        chunk.forEach((t, j) => {
          const r = results[j] ?? null;
          cache.set(t, r);
          if (r) failedAt.delete(tag(t));
          else failedAt.set(tag(t), at);
        });
        if (cancelled) return;
        bump((v) => v + 1);
      }
    })();
    return () => { cancelled = true; };
  }, [texts, enabled, accountId, hint, cache, scope]);

  return cache;
}
