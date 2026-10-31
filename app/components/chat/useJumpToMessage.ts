"use client";

import { useEffect, useRef, useState } from "react";

import { keepChatEntry } from "@/hooks/useChatBackEntry";
import type { useChatMessages } from "@/hooks/useChatMessages";
import type { FanId } from "@/lib/fanId";

import { anchorNext } from "./jumpAnchor";

/** The highlight ring a jump puts on a rendered bubble (search, pinned, ?msg=),
 *  and the ?msg=<id> anchor that pages back to find it. */
export function useJumpToMessage({ accountId, fanId, handle, loadOlder, onJump }: {
  accountId: string;
  fanId: FanId;
  handle: Pick<ReturnType<typeof useChatMessages>, "data" | "isLoading" | "hasOlder" | "isLoadingOlder">;
  loadOlder: () => Promise<unknown>;
  /** A jump happened (ChatSurface closes its search). */
  onJump: () => void;
}) {
  const [highlightId, setHighlightId] = useState<number | null>(null);
  // Which ?msg= target we've already resolved, and how many pages that cost.
  const anchorRef = useRef<string | null>(null);
  const anchorPagesRef = useRef(0);

  function jumpToMessage(id: number) {
    setHighlightId(id);
    onJump();
    // Drop the highlight ring after a couple seconds so it doesn't linger
    // through the next scroll-up that brings it back into view.
    setTimeout(() => setHighlightId((cur) => (cur === id ? null : cur)), 3000);
  }

  // ── ?msg=<id> — open the thread ON a specific message ────────────────────
  //
  // /customs links here so an operator lands on the TIP that bought a custom,
  // not just on the fan. The highlight machinery above only works on a bubble
  // that is RENDERED, and the tip may be well above the first page, so this
  // pages backwards until it finds it.
  //
  // ⚠️ BOUNDED TO ANCHOR_MAX_PAGES, and the bound is the point: every
  // loadOlder() is a live OnlyFans API call, so an unbounded "page until found"
  // turns one click into dozens of upstream requests and a rate-limit risk on a
  // surface an operator clicks repeatedly. Past the bound the thread simply
  // opens where it is — the /customs row already carries the tip's date and
  // amount, so an old one stays findable by hand.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const want = new URLSearchParams(window.location.search).get("msg");
    if (!want) return;
    const key = `${accountId}:${fanId}:${want}`;
    if (anchorRef.current === key) return;   // once per (thread, target)

    const target = String(want);
    const rows = handle.data ?? [];
    const step = anchorNext({
      loading: handle.isLoading,
      found: rows.some((m) => String(m.id) === target),
      pages: anchorPagesRef.current,
      hasOlder: handle.hasOlder,
      loadingOlder: handle.isLoadingOlder,
    });
    if (step === "jump") {
      anchorRef.current = key;
      jumpToMessage(Number(target));
      // Strip the param so a refresh doesn't re-jump out from under a scroll.
      const url = new URL(window.location.href);
      url.searchParams.delete("msg");
      window.history.replaceState(keepChatEntry(), "", url.pathname + (url.search || ""));
      return;
    }
    if (step === "wait") return;
    if (step === "giveUp") {
      anchorRef.current = key;               // give up quietly, stay put
      return;
    }
    anchorPagesRef.current += 1;
    void loadOlder();
  }, [accountId, fanId, handle.data, handle.isLoading, handle.hasOlder,
      handle.isLoadingOlder]);   // eslint-disable-line react-hooks/exhaustive-deps

  return { highlightId, jumpToMessage };
}
