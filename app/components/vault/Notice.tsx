import type { ReactNode } from "react";

const TONE = {
  ok: "border-ok/40 bg-ok/10 text-ok",
  warn: "border-warn/40 bg-warn/10 text-warn",
  err: "border-err/40 bg-err/10 text-err",
} as const;

/** A vault modal's result or error box under its controls: tinted border and text in the tone's colour. */
export function Notice({ tone, children }: { tone: keyof typeof TONE; children: ReactNode }) {
  return <div className={`mt-4 rounded-md border px-3 py-2 ${TONE[tone]}`}>{children}</div>;
}
