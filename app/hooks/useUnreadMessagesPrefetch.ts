"use client";

/**
 * useUnreadMessagesPrefetch — warm the first message page of the top unread
 * chats, so the chats a chatter opens next paint from cache instead of a cold
 * ~600ms OF fetch.
 *
 * Every warm is a real, paid OF call, so the policy is bounded:
 *   • Order: `rows` as the user sees them (the Fan List's sort and narrowing);
 *     a chat counts if `countsAsUnread` (a Fan we restricted never does).
 *   • Tiers: the first as soon as `ready`; each later one only after a quiet
 *     window of its own (the tab visible, no input for PREFETCH_QUIET_MS, then
 *     the browser idle). Nothing past the last tier.
 *   • Never in the user's way: input or a tab switch ends the quiet window and
 *     aborts an idle tier's in-flight warm, which is not retried; an idle tier
 *     never touches a thread that is open or already fetching, and never
 *     cancels a fetch the user has since joined.
 *   • One fetch at a time, on the BACKGROUND lane (`prefetchChatMessages`;
 *     opening a chat mid-warm refetches on the user lane, see useChatMessages).
 *   • Once per (chat, last message): a poll that returns the same rows fires
 *     nothing; a chat re-qualifies only when a NEW message lands in it, which
 *     is exactly when its cached thread went stale. Skipped when the cached
 *     thread already holds that message.
 *   • Only once `ready` (useChatList's `fetchedLive`): a list restored from
 *     disk may show chats long since read. `ready` going false starts no new
 *     warm but does not abort one in flight: only input, a tab switch or
 *     unmount do.
 */

import { useEffect, useRef } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { countsAsUnread } from "@/lib/chatUnread";
import type { FanId } from "@/lib/fanId";
import { onIdle, onUserInput, USER_INPUT_EVENTS } from "@/lib/idle";
import type { OFChatItem, OFMessage } from "@/lib/relay";
import { prefetchChatMessages } from "./useChatMessages";

/** Unread threads warmed per tier, from the top of the list as the user sees it. */
export const UNREAD_PREFETCH_TIERS: readonly number[] = [3, 2, 2];
/** How long the user must do nothing before an idle tier may start. */
export const PREFETCH_QUIET_MS = 2_500;
/** The idle callback's deadline, so a main thread that never idles still lets an idle tier run. */
export const PREFETCH_IDLE_TIMEOUT_MS = 2_000;
/** What interrupts an idle tier: user input, and scroll (a flick's inertia is still the user). */
const INTERRUPTS = [...USER_INPUT_EVENTS, "scroll"];

type Warm = { aid: string; fid: FanId; lastId: number | undefined; key: string };

const threadKey = ({ aid, fid }: Warm) => ["messages", aid, fid] as const;

/** The cached thread already holds the row's last message. */
function threadHolds(qc: QueryClient, w: Warm): boolean {
  const cached = qc.getQueryData<OFMessage[]>(threadKey(w));
  return !!cached?.length && (w.lastId == null || cached.some((m) => String(m.id) === String(w.lastId)));
}

/** Claims `w` for a warm, once ever: false if it was tried before or its
 *  cached thread already holds its last message. Tried even if the warm is
 *  aborted later: retrying is how an abort loops paid calls. */
function claim(qc: QueryClient, tried: Set<string>, w: Warm): boolean {
  if (tried.has(w.key)) return false;
  tried.add(w.key);
  return !threadHolds(qc, w);
}

/** How many views have the thread open. */
function observers(qc: QueryClient, w: Warm): number {
  return qc.getQueryCache().find({ queryKey: threadKey(w), exact: true })?.getObserversCount() ?? 0;
}

/** The thread is open or already fetching: an idle tier leaves it alone. */
function threadBusy(qc: QueryClient, w: Warm): boolean {
  return observers(qc, w) > 0 || (qc.getQueryState(threadKey(w))?.fetchStatus ?? "idle") !== "idle";
}

/** True after a quiet window (the tab visible, no input for PREFETCH_QUIET_MS,
 *  then the browser idle); false as soon as `signal` aborts. Hidden, it waits
 *  for the abort a tab switch sends. */
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

/** `tiers`: threads per tier, the first warmed at once and each later one in a
 *  quiet window of its own; one tier keeps the warm to the first. */
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
    if (!countsAsUnread(c) || !aid || c.withUser?.id == null) continue;
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

  // The first tier: as soon as the list is ready.
  useEffect(() => {
    if (!ready) return;
    for (const w of latest.current.firstTier) {
      if (!claim(qc, tried.current, w)) continue;
      chain.current = chain.current.then(() => prefetchChatMessages(qc, w.aid, w.fid));
    }
  }, [ready, signature, qc]);

  // The idle tiers: one loop, one quiet window per tier. Not keyed on `ready`,
  // so `ready` dropping does not tear the loop down and abort its warm.
  useEffect(() => {
    if (!hasIdleTiers) return;
    let live = true;
    /** The current quiet window and the tier it lets start. */
    let pass = new AbortController();
    const interrupt = () => pass.abort();
    const unlisten = onUserInput(interrupt, INTERRUPTS);
    document.addEventListener("visibilitychange", interrupt);

    /** One idle warm, checked when its link on `chain` starts: input or a tab
     *  switch since its quiet window (`signal`), or `ready` gone, stops it. */
    const warm = async (w: Warm, signal: AbortSignal) => {
      if (signal.aborted || !latest.current.ready) return;
      // The rows may have moved on since the tier was cut: a chat no longer
      // in an idle tier (read meanwhile, say) is skipped and left unclaimed.
      if (!latest.current.idleTiers.some((ws) => ws.some((x) => x.key === w.key))) return;
      if (!claim(qc, tried.current, w) || threadBusy(qc, w)) return;
      // The fetch is ours alone until a view opens the thread and joins it.
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
        // Nothing to warm: re-arm rather than exit. New rows may bring a tier,
        // and restarting the loop for them would abort a warm in flight, which
        // is never retried.
        if (!tier) continue;
        for (const w of tier) {
          // Queued one warm at a time, so a first-tier warm queued meanwhile goes next.
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
