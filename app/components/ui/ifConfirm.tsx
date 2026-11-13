"use client";

/** The app's `confirm()` / `alert()`: the same question in an `IfModal` (Escape or a mask click cancels, Enter on the
 *  focused OK confirms). `<IfConfirmHost/>` (root layout) draws them, one at a time; with no host mounted (unit tests)
 *  they fall back to `window.confirm` / `window.alert`, so a test's mock of those still answers. */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { IfButton } from "@/components/ui/infloww";
import { IfModal } from "@/components/ui/ifModal";

type Ask = { id: number; alert: boolean; message: string; confirmLabel?: string; danger?: boolean; resolve: (ok: boolean) => void };

/** The mounted host's enqueue; null: none mounted. */
let enqueue: ((ask: Ask) => void) | null = null;
/** Each question's id: a fresh dialog (focus, key) per question, even a repeated one. */
let nextId = 0;

export function ifConfirm(message: string, opts: { confirmLabel?: string; danger?: boolean } = {}): Promise<boolean> {
  const push = enqueue;
  if (!push) return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => push({ id: ++nextId, alert: false, message, ...opts, resolve }));
}

export function ifAlert(message: string): Promise<void> {
  const push = enqueue;
  if (!push) {
    window.alert(message);
    return Promise.resolve();
  }
  return new Promise((resolve) => push({ id: ++nextId, alert: true, message, resolve: () => resolve() }));
}

export function IfConfirmHost() {
  const [queue, setQueue] = useState<Ask[]>([]);
  useEffect(() => {
    const mine = (ask: Ask) => setQueue((q) => [...q, ask]);
    enqueue = mine;
    return () => {
      if (enqueue === mine) enqueue = null;
    };
  }, []);
  const ask = queue[0];
  if (!ask) return null;
  const answer = (ok: boolean) => {
    ask.resolve(ok);
    // A double click answers once: only this question leaves.
    setQueue((q) => (q[0] === ask ? q.slice(1) : q));
  };
  // On <body>, after every layer already open (a Radix portal, a nested modal): it stacks and takes keys on top.
  return createPortal(
    <IfModal
      key={ask.id}
      label={ask.alert ? "Notice" : "Confirm"}
      describedBy={`if-confirm-${ask.id}`}
      width={416}
      closable={false}
      keyboard
      maskClosable
      onClose={() => answer(false)}
      footer={
        <>
          {!ask.alert && <IfButton onClick={() => answer(false)}>Cancel</IfButton>}
          <IfButton
            variant="primary"
            className={ask.danger ? "bg-err hover:bg-err/90" : undefined}
            autoFocus
            onClick={() => answer(true)}
          >
            {ask.alert ? "OK" : (ask.confirmLabel ?? "OK")}
          </IfButton>
        </>
      }
    >
      <p id={`if-confirm-${ask.id}`} className="whitespace-pre-line break-words">{ask.message}</p>
    </IfModal>,
    document.body,
  );
}
