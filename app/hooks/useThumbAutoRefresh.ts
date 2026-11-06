"use client";

/**
 * useThumbAutoRefresh — a vault grid reloads itself when its thumbnails break.
 *
 * A tile's picture is a time-signed OnlyFans CDN url (live path, through /img) or the mirror's still
 * (/admin/vault-ai/thumb). A listing held long enough (React Query's 3-day staleTime, the relay's day-long
 * vault_cache) carries urls whose signature has expired: OF answers 403, the tile shows a broken image. The
 * owner's rule: a broken top image means reload. So:
 *   • each tile whose <img> errors reports its id and that src (`broken`) and shows its placeholder until a reload; the reload
 *     fires DEBOUNCE_MS after the latest newly broken tile, so a screenful of broken tiles costs ONE reload (`fire`);
 *   • at most one reload per COOLDOWN_MS per Creator, enforced in ONE place, `thumbCooldown.claim` (module level):
 *     a remount, a reopened picker or a second grid of the same Creator waits it out too, and a CDN that stays down
 *     can never loop. A tile broken during the cooldown is retried when it ends;
 *   • the reload is `reloadBrokenThumbs` (hooks/vaultRefresh): the mirror's items, or the live listing past the
 *     relay's cache; never a full OF sync;
 *   • once the reload's refetch settled (`fire` waits for it: retried earlier, a tile would ask for its old,
 *     expired url again and break anew), and only if the grid still shows the Creator it was for (`fire.scope`),
 *     the ids it answered get its `nonce` on their src (`retrySrc`), so a url
 *     the reload did not change (the mirror's stable thumb route) is still asked for again instead of the browser
 *     keeping the failure. A tile's nonce never goes down: a later reload of other tiles leaves it on the src
 *     that loaded;
 *   • a tile is retried at most once per mount: broken again after its retry (media deleted on OF, a thumb that
 *     never renders), no further reload (else the grid would reload every COOLDOWN_MS) and its placeholder shows
 *     while its src is still the one that failed (`failed`); a new url (after a Refresh) is drawn again;
 *   • `reset` on a new scope (another Creator, the picker closed or reopened); the cooldown stays.
 */

import { useCallback, useEffect, useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { reloadBrokenThumbs, type ThumbSource } from "@/hooks/vaultRefresh";

export const DEBOUNCE_MS = 400;
export const COOLDOWN_MS = 5 * 60_000;

export interface ThumbRefreshState {
  /** The Creator the grid shows (null: none); a `fire` for another one is stale and ignored. */
  scope: string | null;
  /** Broken since the last reload, waiting for the next one: their tiles show the placeholder. */
  pending: readonly string[];
  /** Per tile, the reload its src carries (`_r=`). Set once: a retried tile is not retried again. */
  nonces: Readonly<Record<string, number>>;
  /** Bumps each time a reload fires. */
  nonce: number;
  /** Per retried tile that broke again, the src that failed: its placeholder shows while that is still its src. */
  failed: Readonly<Record<string, string>>;
}

export type ThumbRefreshAction =
  /** Tile `id`'s <img> failed to load `src`. */
  | { type: "broken"; id: string; src: string }
  /** A reload for Creator `scope` settled (the cooldown was claimed before it started). */
  | { type: "fire"; scope: string }
  | { type: "reset"; scope: string | null };

export const INITIAL_THUMB_REFRESH: ThumbRefreshState = { scope: null, pending: [], nonces: {}, nonce: 0, failed: {} };

/** The last reload is at least COOLDOWN_MS old (or there was none). */
export function cooledDown(lastAt: number | null, now: number): boolean {
  return lastAt === null || now - lastAt >= COOLDOWN_MS;
}

/** How long until the reload may fire: the debounce, or the rest of the cooldown when that is longer. */
export function fireDelay(lastAt: number | null, now: number): number {
  return Math.max(DEBOUNCE_MS, lastAt === null ? 0 : lastAt + COOLDOWN_MS - now);
}

export function thumbRefreshReducer(s: ThumbRefreshState, a: ThumbRefreshAction): ThumbRefreshState {
  switch (a.type) {
    case "broken":
      if (s.pending.includes(a.id)) return s;
      // Already retried once (R3-1): no further reload for it, just its placeholder for this src (R4-1).
      if (a.id in s.nonces) return s.failed[a.id] === a.src ? s : { ...s, failed: { ...s.failed, [a.id]: a.src } };
      return { ...s, pending: [...s.pending, a.id] };
    case "fire": {
      if (a.scope !== s.scope || s.pending.length === 0) return s;
      const nonce = s.nonce + 1;
      const nonces = { ...s.nonces };
      for (const id of s.pending) nonces[id] = nonce;
      return { ...s, pending: [], nonces, nonce };
    }
    case "reset":
      return { ...INITIAL_THUMB_REFRESH, scope: a.scope };
  }
}

/** `src` asked for again after reload `nonce` (0: as is). */
export function retrySrc(src: string, nonce: number): string {
  if (!src || nonce <= 0) return src;
  return `${src}${src.includes("?") ? "&" : "?"}_r=${nonce}`;
}

/** What tile `id` shows for `src`: "" (the placeholder) while it waits for a reload or its src is the one that
 *  failed after its retry, else src with its nonce. */
export function thumbSrc(s: ThumbRefreshState, id: string, src: string): string {
  if (!src || s.pending.includes(id)) return "";
  const out = retrySrc(src, s.nonces[id] ?? 0);
  return out === s.failed[id] ? "" : out;
}

// Per Creator, when its last reload fired (epoch ms). Module-level on purpose: outlives every grid.
const lastReloadAt = new Map<string, number>();
export const thumbCooldown = {
  lastAt: (accountId: string): number | null => lastReloadAt.get(accountId) ?? null,
  /** The cooldown's one check: true (and marked `now`) when this Creator may reload now, else false. */
  claim: (accountId: string, now: number): boolean => {
    if (!cooledDown(lastReloadAt.get(accountId) ?? null, now)) return false;
    lastReloadAt.set(accountId, now);
    return true;
  },
};

/** A grid's tiles read their src through `thumbFor` and report a failed load (of the src it gave) to `onBroken`. */
export interface ThumbRetry {
  thumbFor: (id: string | number, src: string) => string;
  onBroken: (id: string | number, src: string) => void;
}

export function useThumbAutoRefresh(accountId: string | null, source: ThumbSource): ThumbRetry {
  const qc = useQueryClient();
  const [s, dispatch] = useReducer(thumbRefreshReducer, accountId, (scope) => ({ ...INITIAL_THUMB_REFRESH, scope }));
  useEffect(() => {
    dispatch({ type: "reset", scope: accountId });
  }, [accountId]);
  const { pending } = s;
  useEffect(() => {
    if (!accountId || pending.length === 0) return;
    let t: ReturnType<typeof setTimeout>;
    const arm = () => {
      t = setTimeout(() => {
        if (!thumbCooldown.claim(accountId, Date.now())) return arm(); // another grid of this Creator reloaded meanwhile
        void reloadBrokenThumbs(qc, accountId, source).finally(() => dispatch({ type: "fire", scope: accountId }));
      }, fireDelay(thumbCooldown.lastAt(accountId), Date.now()));
    };
    arm();
    return () => clearTimeout(t);
  }, [pending, accountId, source, qc]);
  const onBroken = useCallback(
    (id: string | number, src: string) => dispatch({ type: "broken", id: String(id), src }), []);
  const thumbFor = useCallback((id: string | number, src: string) => thumbSrc(s, String(id), src), [s]);
  return { thumbFor, onBroken };
}
