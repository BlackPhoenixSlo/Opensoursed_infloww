"use client";


import { useCallback, useEffect, useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { reloadBrokenThumbs, type VaultSource } from "@/hooks/vaultRefresh";
import { vaultTileThumb } from "@/lib/mediaUrl";
import { type VaultMedia } from "@/lib/relay";

export const DEBOUNCE_MS = 400;
export const COOLDOWN_MS = 5 * 60_000;

export interface ThumbRefreshState {
  scope: string | null;
  pending: readonly string[];
  nonces: Readonly<Record<string, number>>;
  nonce: number;
  failed: Readonly<Record<string, string>>;
}

export type ThumbRefreshAction =
  | { type: "broken"; id: string; src: string; gaveUp?: boolean }
  | { type: "fire"; scope: string }
  | { type: "refreshed"; scope: string }
  | { type: "reset"; scope: string | null };

export const INITIAL_THUMB_REFRESH: ThumbRefreshState = { scope: null, pending: [], nonces: {}, nonce: 0, failed: {} };

export function cooledDown(lastAt: number | null, now: number): boolean {
  return lastAt === null || now - lastAt >= COOLDOWN_MS;
}

export function fireDelay(lastAt: number | null, now: number): number {
  return Math.max(DEBOUNCE_MS, lastAt === null ? 0 : lastAt + COOLDOWN_MS - now);
}

export function thumbRefreshReducer(s: ThumbRefreshState, a: ThumbRefreshAction): ThumbRefreshState {
  switch (a.type) {
    case "broken":
      if (s.pending.includes(a.id)) return s;
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

export function retrySrc(src: string, nonce: number): string {
  if (!src || nonce <= 0) return src;
  return `${src}${src.includes("?") ? "&" : "?"}_r=${nonce}`;
}

export function thumbSrc(s: ThumbRefreshState, id: string, src: string): string {
  if (!src || s.pending.includes(id)) return "";
  const out = retrySrc(src, s.nonces[id] ?? 0);
  return out === s.failed[id] ? "" : out;
}

const lastReloadAt = new Map<string, number>();
export const thumbCooldown = {
  lastAt: (accountId: string): number | null => lastReloadAt.get(accountId) ?? null,
  claim: (accountId: string, now: number): boolean => {
    if (!cooledDown(lastReloadAt.get(accountId) ?? null, now)) return false;
    lastReloadAt.set(accountId, now);
    return true;
  },
};

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
        if (!thumbCooldown.claim(accountId, Date.now())) return arm();
        void reloadBrokenThumbs(qc, accountId, source).finally(() => dispatch({ type: "fire", scope: accountId }));
      }, fireDelay(thumbCooldown.lastAt(accountId), Date.now()));
    };
    arm();
    return () => clearTimeout(t);
  }, [pending, accountId, source, qc]);
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
