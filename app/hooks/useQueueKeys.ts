"use client";


import { useEffect, useRef } from "react";

import { type FanId } from "@/lib/fanId";

export function useQueueKeys({ accountId, fanId, held, onAdvance, onHoldChange, enterAdvances = false }: {
  accountId: string | null;
  fanId: FanId | null;
  held: boolean;
  onAdvance?: (dir: 1 | -1) => void;
  onHoldChange?: (held: boolean) => void;
  enterAdvances?: boolean;
}) {
  const holdRef = useRef(onHoldChange);
  useEffect(() => { holdRef.current = onHoldChange; });
  useEffect(() => { holdRef.current?.(held); }, [held]);
  useEffect(() => () => holdRef.current?.(false), []);
  const heldRef = useRef(held);
  useEffect(() => { heldRef.current = held; }, [held]);
  const fanKey = `${accountId}:${fanId}`;
  const onFanRef = useRef<string | null>(fanKey);
  useEffect(() => { onFanRef.current = fanKey; }, [fanKey]);
  useEffect(() => () => { onFanRef.current = null; }, []);

  const isAdvanceKey = (e: React.KeyboardEvent) =>
    !!onAdvance && (e.metaKey || e.ctrlKey || (enterAdvances && e.key === "Enter")) && !e.altKey && !e.shiftKey;

  function arrowKey(e: React.KeyboardEvent, empty: boolean) {
    if (onAdvance && (e.key === "ArrowRight" || e.key === "ArrowLeft")
      && !e.altKey && !e.shiftKey && !e.repeat && !e.nativeEvent.isComposing
      && !held && (e.metaKey || e.ctrlKey || empty)) {
      e.preventDefault();
      onAdvance(e.key === "ArrowRight" ? 1 : -1);
    }
  }

  function advanceAfter(sending: void | PromiseLike<unknown>, scheduled: boolean) {
    if (!scheduled || !sending) return onAdvance?.(1);
    const from = onFanRef.current;
    sending.then(() => {
      if (from !== null && onFanRef.current === from && !heldRef.current) onAdvance?.(1);
    }, () => {});
  }

  return { isAdvanceKey, arrowKey, advanceAfter };
}
