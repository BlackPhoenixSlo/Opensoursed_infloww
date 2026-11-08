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
 *   • a tile is retried at most once: broken again after its retry (media deleted on OF, a thumb that never
 *     renders), no further reload (else the grid would reload every COOLDOWN_MS) and its placeholder shows while
 *     its src is still the one that failed (`failed`). That give-up is module-level per Creator too (`thumbGiveUp`),
 *     so a reopened picker or a remounted grid spends no reload (a relay vault-cache drop) on it again;
 *   • the user's Refresh (`refreshed`, once it settled) is the retry of every tile given up on or waiting: each is
 *     asked for again on a new nonce (the mirror's thumb url is stable, so without one it would keep its
 *     placeholder), and the give-ups are forgotten;
 *   • `reset` on a new scope (another Creator, the picker closed or reopened); the cooldown and give-ups stay.
 */

import { useCallback, useEffect, useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { reloadBrokenThumbs, type VaultSource } from "@/hooks/vaultRefresh";
import { vaultTileThumb } from "@/lib/mediaUrl";
import { type VaultMedia } from "@/lib/relay";

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
  /** Tile `id`'s <img> failed to load `src`; `gaveUp`: given up on in an earlier mount (`thumbGiveUp`). */
  | { type: "broken"; id: string; src: string; gaveUp?: boolean }
  /** A reload for Creator `scope` settled (the cooldown was claimed before it started). */
  | { type: "fire"; scope: string }
  /** The user's Refresh of Creator `scope` settled: it was the reload of every tile waiting or given up on. */
  | { type: "refreshed"; scope: string }
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
      // Already retried once (R3-1), in this mount or an earlier one (F7): no further reload for it, just its
      // placeholder for this src (R4-1).
      if (a.id in s.nonces || a.gaveUp) return s.failed[a.id] === a.src ? s : { ...s, failed: { ...s.failed, [a.id]: a.src } };
      return { ...s, pending: [...s.pending, a.id] };
    case "fire": {
      if (a.scope !== s.scope || s.pending.length === 0) return s;
      const nonce = s.nonce + 1;
      const nonces = { ...s.nonces };
      for (const id of s.pending) nonces[id] = nonce;
      return { ...s, pending: [], nonces, nonce };
    }
    case "refreshed": {
      // A new nonce, so a stable url is asked for again rather than the src that failed (F8); broken again, the
      // tile stays given up: the Refresh was its retry.
      const ids = [...s.pending, ...Object.keys(s.failed)];
      if (a.scope !== s.scope || ids.length === 0) return s;
      const nonce = s.nonce + 1;
      const nonces = { ...s.nonces };
      for (const id of ids) nonces[id] = nonce;
      return { ...s, pending: [], nonces, nonce, failed: {} };
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

// Per Creator, the tiles given up on (broken again after their retry). Module-level like the cooldown: outlives
// every grid, until the user's Refresh.
const gaveUp = new Map<string, Set<string>>();
export const thumbGiveUp = {
  has: (accountId: string, id: string): boolean => gaveUp.get(accountId)?.has(id) ?? false,
  add: (accountId: string, id: string): void => {
    const ids = gaveUp.get(accountId) ?? new Set<string>();
    ids.add(id);
    gaveUp.set(accountId, ids);
  },
  clear: (accountId: string): void => { gaveUp.delete(accountId); },
};

/** A grid's thumbnail retry: `tile(m)` is what tile `m`'s <img> shows ("" = its placeholder) and its onError;
 *  `refreshed(accountId)` once the user's Refresh of that Creator settled. */
export interface ThumbRetry {
  tile: (m: VaultMedia) => { src: string; onError: () => void };
  refreshed: (accountId: string) => void;
}

export function useThumbAutoRefresh(accountId: string | null, source: VaultSource): ThumbRetry {
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
  // A give-up outlives the mount (F7): recorded once the tile is drawn as failed.
  const { scope, failed } = s;
  useEffect(() => {
    if (scope) for (const id of Object.keys(failed)) thumbGiveUp.add(scope, id);
  }, [scope, failed]);
  const tile = useCallback((m: VaultMedia) => {
    const id = String(m.id);
    const src = thumbSrc(s, id, vaultTileThumb(m, accountId));
    const onError = () => dispatch({ type: "broken", id, src, gaveUp: !!accountId && thumbGiveUp.has(accountId, id) });
    return { src, onError };
  }, [s, accountId]);
  const refreshed = useCallback((scope: string) => {
    thumbGiveUp.clear(scope);
    dispatch({ type: "refreshed", scope });
  }, []);
  return { tile, refreshed };
}
