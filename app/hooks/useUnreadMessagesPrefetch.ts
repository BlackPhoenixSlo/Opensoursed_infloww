"use client";


import { useEffect, useRef } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { excludedFromBadges, isUnreadChat } from "@/lib/chatUnread";
import type { FanId } from "@/lib/fanId";
import { onIdle, onUserInput, USER_INPUT_EVENTS } from "@/lib/idle";
import type { OFChatItem, OFMessage } from "@/lib/relay";
import { prefetchChatMessages } from "./useChatMessages";

export const UNREAD_PREFETCH_TIERS: readonly number[] = [3, 2, 2];
export const UNREAD_WARM_REUSE_MS = 20_000;
export const PREFETCH_QUIET_MS = 2_500;
export const PREFETCH_IDLE_TIMEOUT_MS = 2_000;
const INTERRUPTS = [...USER_INPUT_EVENTS, "scroll"];

type Warm = { aid: string; fid: FanId; lastId: number | undefined; key: string };

const threadKey = ({ aid, fid }: Warm) => ["messages", aid, fid] as const;

function threadHolds(qc: QueryClient, w: Warm): boolean {
  const cached = qc.getQueryData<OFMessage[]>(threadKey(w));
  return !!cached?.length && (w.lastId == null || cached.some((m) => String(m.id) === String(w.lastId)));
}

// Claimed once ever, even if aborted: retrying an abort loops paid OF calls.
function claim(qc: QueryClient, tried: Set<string>, w: Warm): boolean {
  if (tried.has(w.key)) return false;
  tried.add(w.key);
  return !threadHolds(qc, w);
}

function observers(qc: QueryClient, w: Warm): number {
  return qc.getQueryCache().find({ queryKey: threadKey(w), exact: true })?.getObserversCount() ?? 0;
}

function threadBusy(qc: QueryClient, w: Warm): boolean {
  return observers(qc, w) > 0 || (qc.getQueryState(threadKey(w))?.fetchStatus ?? "idle") !== "idle";
}

function quietWindow(signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    let cancelIdle = () => {};
    const done = (quiet: boolean) => {
      clearTimeout(timer);
      cancelIdle();
      signal.removeEventListener("abort", interrupted);
      resolve(quiet);
    };
    const interrupted = () => done(false);
    const timer = document.hidden
      ? undefined
      : setTimeout(() => { cancelIdle = onIdle(() => done(true), PREFETCH_IDLE_TIMEOUT_MS); }, PREFETCH_QUIET_MS);
    signal.addEventListener("abort", interrupted);
  });
}

export function useUnreadMessagesPrefetch(
  rows: OFChatItem[],
  ready: boolean,
  tiers: readonly number[] = UNREAD_PREFETCH_TIERS,
) {
  const qc = useQueryClient();
  const tried = useRef(new Set<string>());
  const chain = useRef<Promise<void>>(Promise.resolve());

  const [first = 0, ...idle] = tiers;
  const total = idle.reduce((a, b) => a + b, first);
  const top: Warm[] = [];
  for (const c of rows) {
    if (top.length >= total) break;
    const aid = c.__accountId;
    if (!isUnreadChat(c) || excludedFromBadges(c) || !aid || c.withUser?.id == null) continue;
    const lastId = c.lastMessage?.id;
    top.push({ aid, fid: c.withUser.id, lastId, key: `${aid}:${c.withUser.id}:${lastId ?? ""}` });
  }
  const idleTiers: Warm[][] = [];
  let at = first;
  for (const n of idle) {
    idleTiers.push(top.slice(at, at + n));
    at += n;
  }
  const latest = useRef({ firstTier: top.slice(0, first), idleTiers, ready });
  latest.current = { firstTier: top.slice(0, first), idleTiers, ready };
  const signature = top.map((t) => t.key).join(",");
  const hasIdleTiers = idle.length > 0;

  useEffect(() => {
    if (!ready) return;
    for (const w of latest.current.firstTier) {
      if (!claim(qc, tried.current, w)) continue;
      chain.current = chain.current.then(() => prefetchChatMessages(qc, w.aid, w.fid));
    }
  }, [ready, signature, qc]);

  useEffect(() => {
    if (!hasIdleTiers) return;
    let live = true;
    let pass = new AbortController();
    const interrupt = () => pass.abort();
    const unlisten = onUserInput(interrupt, INTERRUPTS);
    document.addEventListener("visibilitychange", interrupt);

    const warm = async (w: Warm, signal: AbortSignal) => {
      if (signal.aborted || !latest.current.ready) return;
      if (!latest.current.idleTiers.some((ws) => ws.some((x) => x.key === w.key))) return;
      if (!claim(qc, tried.current, w) || threadBusy(qc, w)) return;
      const cancel = () => {
        if (observers(qc, w) === 0) void qc.cancelQueries({ queryKey: threadKey(w), exact: true });
      };
      signal.addEventListener("abort", cancel);
      await prefetchChatMessages(qc, w.aid, w.fid);
      signal.removeEventListener("abort", cancel);
    };

    void (async () => {
      while (live) {
        pass = new AbortController();
        const { signal } = pass;
        if (!(await quietWindow(signal))) continue;
        const tier = latest.current.idleTiers.find((ws) => ws.some((w) => !tried.current.has(w.key)));
        if (!tier) continue;
        for (const w of tier) {
          const step = chain.current.then(() => warm(w, signal));
          chain.current = step;
          await step;
        }
      }
    })();

    return () => {
      live = false;
      pass.abort();
      unlisten();
      document.removeEventListener("visibilitychange", interrupt);
    };
  }, [hasIdleTiers, qc]);
}
