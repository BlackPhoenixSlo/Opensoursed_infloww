"use client";

import { useEffect, useRef, useState } from "react";

import { keepChatEntry } from "@/hooks/useChatBackEntry";
import type { useChatMessages } from "@/hooks/useChatMessages";
import type { FanId } from "@/lib/fanId";

import { anchorNext } from "./jumpAnchor";

export function useJumpToMessage({ accountId, fanId, handle, loadOlder, onJump }: {
  accountId: string;
  fanId: FanId;
  handle: Pick<ReturnType<typeof useChatMessages>, "data" | "isLoading" | "hasOlder" | "isLoadingOlder" | "olderFailed">;
  loadOlder: () => Promise<unknown>;
  onJump: () => void;
}) {
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const anchorRef = useRef<string | null>(null);
  const anchorPagesRef = useRef(0);

  function jumpToMessage(id: number) {
    setHighlightId(id);
    onJump();
    setTimeout(() => setHighlightId((cur) => (cur === id ? null : cur)), 3000);
  }

  useEffect(() => {
    if (typeof window === "undefined") return;
    const want = new URLSearchParams(window.location.search).get("msg");
    if (!want) return;
    const key = `${accountId}:${fanId}:${want}`;
    if (anchorRef.current === key) return;

    // Bounded by ANCHOR_MAX_PAGES: each loadOlder is a live OF API call, unbounded paging risks rate limits.
    const target = String(want);
    const rows = handle.data ?? [];
    const step = anchorNext({
      loading: handle.isLoading,
      found: rows.some((m) => String(m.id) === target),
      pages: anchorPagesRef.current,
      hasOlder: handle.hasOlder && !handle.olderFailed,
      loadingOlder: handle.isLoadingOlder,
    });
    if (step === "jump") {
      anchorRef.current = key;
      jumpToMessage(Number(target));
      const url = new URL(window.location.href);
      url.searchParams.delete("msg");
      window.history.replaceState(keepChatEntry(), "", url.pathname + (url.search || ""));
      return;
    }
    if (step === "wait") return;
    if (step === "giveUp") {
      anchorRef.current = key;
      return;
    }
    anchorPagesRef.current += 1;
    void loadOlder().catch(() => {});
  }, [accountId, fanId, handle.data, handle.isLoading, handle.hasOlder,
      handle.isLoadingOlder, handle.olderFailed]);   // eslint-disable-line react-hooks/exhaustive-deps

  return { highlightId, jumpToMessage };
}
