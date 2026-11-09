"use client";

import { useState, type ReactNode } from "react";

import { IfButton, IfModal } from "@/components/ui/infloww";

/** antd's `Modal.confirm` as an awaited `IfModal` (416px): `ask(title, body, ok)` resolves true on the primary
 *  button, false on Cancel, ×, or Escape. Render `modal` once in the component. */
export function useIfConfirm() {
  const [q, setQ] = useState<{ title: string; body?: ReactNode; ok: string; resolve: (yes: boolean) => void } | null>(null);
  const ask = (title: string, body?: ReactNode, ok = "Confirm") =>
    new Promise<boolean>((resolve) => setQ({ title, body, ok, resolve }));
  const done = (yes: boolean) => { q?.resolve(yes); setQ(null); };
  const modal = q && (
    <IfModal
      title={q.title}
      width={416}
      onClose={() => done(false)}
      footer={(
        <>
          <IfButton onClick={() => done(false)}>Cancel</IfButton>
          <IfButton variant="primary" onClick={() => done(true)}>{q.ok}</IfButton>
        </>
      )}
    >
      {q.body}
    </IfModal>
  );
  return { ask, modal };
}
