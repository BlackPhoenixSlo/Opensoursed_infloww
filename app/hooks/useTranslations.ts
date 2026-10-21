"use client";

/**
 * useTranslations — batch-fetch English translations for chat bubble texts
 * via the relay's POST /admin/translate (Google's free gtx endpoint,
 * proxied server-side because the browser can't reach it cross-origin).
 *
 * Keyed by the STRIPPED text (not message id) so translations survive
 * optimistic-id churn and repeat texts across fans cost one fetch. The
 * module-level cache lives for the tab's lifetime; the relay keeps its own
 * cross-session cache on top.
 *
 * A `null` cache entry means "tried and failed" — we deliberately don't
 * retry within the session so a rate-limited Google endpoint degrades to
 * originals instead of a request storm.
 */

import { useEffect, useState } from "react";

import { relay } from "@/lib/relay";

export interface BubbleTranslation {
  /** English translation of the bubble text. */
  text: string;
  /** Detected ISO 639-1 source language ("es", "en", …). */
  lang: string;
}

const CHUNK = 40;

const cache = new Map<string, BubbleTranslation | null>();
const inFlight = new Set<string>();

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
): Map<string, BubbleTranslation | null> {
  const [, bump] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const missing = Array.from(new Set(texts)).filter(
      (t) => t && !cache.has(t) && !inFlight.has(t),
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
        chunk.forEach((t) => inFlight.add(t));
        try {
          const resp = await relay.post<{ results: Array<BubbleTranslation | null> }>(
            "/admin/translate",
            { texts: chunk, target: "en" },
            { accountId },
          );
          chunk.forEach((t, j) => cache.set(t, resp.results?.[j] ?? null));
        } catch {
          chunk.forEach((t) => cache.set(t, null));
        } finally {
          chunk.forEach((t) => inFlight.delete(t));
        }
        if (cancelled) return;
        bump((v) => v + 1);
      }
    })();
    return () => { cancelled = true; };
  }, [texts, enabled, accountId]);

  return cache;
}
