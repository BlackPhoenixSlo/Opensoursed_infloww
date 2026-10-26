"use client";

/**
 * useQueueKeys — the Composer's queue keys (`onAdvance`):
 * ⌘/Ctrl+Enter sends, then moves to the next Fan; → / ← move when the
 * composer is empty, ⌘/Ctrl+→ / ← over a text draft (it is kept per Fan),
 * never away from what the per-Fan draft can't keep (`held`: media, GIFs,
 * uploads or a price), which is reported through `onHoldChange` (false on
 * unmount). Without `onAdvance` no key moves.
 */

import { useEffect, useRef } from "react";

import { type FanId } from "@/lib/fanId";

export function useQueueKeys({ accountId, fanId, held, onAdvance, onHoldChange }: {
  accountId: string | null;
  fanId: FanId | null;
  held: boolean;
  onAdvance?: (dir: 1 | -1) => void;
  onHoldChange?: (held: boolean) => void;
}) {
  const holdRef = useRef(onHoldChange);
  useEffect(() => { holdRef.current = onHoldChange; });
  useEffect(() => { holdRef.current?.(held); }, [held]);
  useEffect(() => () => holdRef.current?.(false), []);
  const heldRef = useRef(held);
  useEffect(() => { heldRef.current = held; }, [held]);
  // The Fan this composer is on now; null once unmounted.
  const fanKey = `${accountId}:${fanId}`;
  const onFanRef = useRef<string | null>(fanKey);
  useEffect(() => { onFanRef.current = fanKey; }, [fanKey]);
  useEffect(() => () => { onFanRef.current = null; }, []);

  /** Whether this Enter sends and moves on: ⌘/Ctrl, never with Alt (AltGr)
   *  or Shift. */
  const isAdvanceKey = (e: React.KeyboardEvent) =>
    !!onAdvance && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;

  /** → / ←: moves and takes the key when allowed (`empty`: no text, no
   *  quote). */
  function arrowKey(e: React.KeyboardEvent, empty: boolean) {
    if (onAdvance && (e.key === "ArrowRight" || e.key === "ArrowLeft")
      && !e.altKey && !e.shiftKey && !e.repeat && !e.nativeEvent.isComposing
      && !held && (e.metaKey || e.ctrlKey || empty)) {
      e.preventDefault();
      onAdvance(e.key === "ArrowRight" ? 1 : -1);
    }
  }

  /** ⌘/Ctrl+Enter's move to the next Fan, as the send begins: an immediate
   *  send moves at once (the parent marked it in flight, so the queue's step
   *  passes over this Fan; a failure brings him back); a scheduled one once
   *  enqueued (a refused one stays, restored), and only while this composer
   *  is still mounted on the Fan it was sent from (the chatter may have
   *  moved) and holds nothing new (media or a price added while it was
   *  enqueued). `sending` is what `onSend` returned: no promise means
   *  nothing to wait for. */
  function advanceAfter(sending: void | PromiseLike<unknown>, scheduled: boolean) {
    if (!scheduled || !sending) return onAdvance?.(1);
    const from = onFanRef.current;
    sending.then(() => {
      if (from !== null && onFanRef.current === from && !heldRef.current) onAdvance?.(1);
    }, () => {});
  }

  return { isAdvanceKey, arrowKey, advanceAfter };
}
