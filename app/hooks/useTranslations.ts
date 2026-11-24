"use client";

/**
 * useTranslations — batch-fetch English translations for chat bubble texts
 * via the relay's POST /admin/translate (Google's free gtx endpoint,
 * proxied server-side because the browser can't reach it cross-origin).
 *
 * Keyed by the STRIPPED text (not message id) so translations survive
 * optimistic-id churn. Unhinted answers are scoped to the account and fan. The
 * module-level cache lives for the tab's lifetime; the relay keeps its own
 * cross-session cache on top.
 *
 * A `null` cache entry can be retried when the effect runs again and
 * FAILED_RETRY_MS has elapsed.
 *
 * `hint` is the Fan's language when the chatter set one: the relay translates
 * one- or two-word texts from it, since Google misreads them ("Ja" → "And").
 * Answers depend on it, so each hint has its own cache.
 */

import { useEffect, useState } from "react";

import type { FanId } from "@/lib/fanId";
import { relay } from "@/lib/relay";

export interface BubbleTranslation {
  /** English translation of the bubble text. */
  text: string;
  /** Detected ISO 639-1 source language ("es", "en", …). */
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

/** Tests only: every hint's cache, failures and in-flight marks. */
export function resetTranslationsForTests() {
  caches.clear();
  failedAt.clear();
  inFlight.clear();
}

/** `accountId` is the chat's Creator, sent as `X-Account-Id` so the Relay's
 *  AI translation gate reads that Creator's Agency (spec phase-04, story 57).
 *
 *  ASSUMPTION: the translate request names the chat's Creator in
 *  `X-Account-Id`, as the Applied settings read does. Rung 3 (house
 *  precedent, `relay.get(..., { accountId })` in lib/appliedSettings.ts) and
 *  rung 4. Side effect: a chatter naming a Creator it may not access now gets
 *  403 from `agency_contexts` on a route that used to answer, and its bubbles
 *  show "No translation available". Overturned if the gate should read the
 *  chatter's Agencies without a Creator in scope. */
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
        // Acquire inFlight per-CHUNK, not upfront: the invariant is "inFlight
        // only holds texts with a request actually in the air". Acquiring the
        // whole `missing` list here used to leak every not-yet-fetched chunk
        // when `cancelled` fired mid-run (each poll/SSE refresh re-runs the
        // effect), permanently blocking the tail of any >40-text thread from
        // ever translating. Worst case now is a bounded duplicate fetch when
        // two runs overlap — idempotent (same cache.set, relay caches too).
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
