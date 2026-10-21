"use client";

/** Small shared bits for the Growth tabs (Trial / Tracking / Promotion).
 *
 *  The last-run line every automation surface renders is NOT here any more — it
 *  is `@/lib/runStats`, because the Brain's welcome card renders it too and this
 *  module's leading underscore says "internal to this folder". Nothing forwards
 *  it any more — import `RunStats` / `runStatsChunks` / `isDryRun` from
 *  `@/lib/runStats` directly; the compatibility re-export that stood here while
 *  the importers were repointed is gone. */

import { useState, type ReactNode } from "react";
import { Button, Input } from "@/components/ui/primitives";
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

export function fmtUsd(cents: number): string {
  return `$${(Math.max(0, cents) / 100).toFixed(2)}`;
}


/** Message off a thrown value, with a fallback — collapses the
 *  `(e as Error)?.message || "…"` cast every Growth create/save catch repeated. */
export function errMsg(e: unknown, fallback: string): string {
  return (e as Error)?.message || fallback;
}

export function Field({
  label, children,
}: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] uppercase tracking-wide text-fg-dim">{label}</span>
      {children}
    </label>
  );
}

export function NumInput({
  value, onChange, min = 0, className,
}: { value: number; onChange: (v: number) => void; min?: number; className?: string }) {
  // Hold the raw keystrokes. Binding the number straight to the input let a
  // field sitting at 0 render "040" once you typed 40 in front of it, and made
  // the box impossible to clear while typing. The draft keeps typing natural;
  // blur normalises it back to the real number.
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <Input
      type="number" min={min} className={className}
      value={draft ?? String(value)}
      onChange={(e) => {
        const raw = e.target.value;
        setDraft(raw);
        const n = Number(raw);
        if (raw !== "" && Number.isFinite(n)) onChange(n);
      }}
      onBlur={() => setDraft(null)}
    />
  );
}

/** A native select over `{value, label}` options (OF's / Infloww's dropdown lists), numbers in and out. */
export function SelectInput({
  value, options, onChange, ariaLabel, disabled,
}: {
  value: number;
  options: { value: string; label: string }[];
  onChange: (v: number) => void;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  return (
    <select
      aria-label={ariaLabel}
      disabled={disabled}
      className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent disabled:opacity-50"
      value={String(value)}
      onChange={(e) => onChange(Number(e.target.value))}
    >
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

// ── Automation last-run stats live in `@/lib/runStats` ────────────────
//
// `isDryRun`, `runStatsChunks`, `welcomeStatsChunks`, `RunStats` and `StatChunk`
// were here. `RunStats` is not growth-only — the Brain's welcome card renders it
// too, and reaching across the folder boundary for an underscore-prefixed module
// is the seam a welcome bag came through into the auto_follow formatter. A
// compatibility re-export stood here while the importers were repointed; it is
// gone, so `_bits`'s underscore means what it says again: growth-local only.

/** Danger button that guards a delete behind a native confirm. Every Growth
 *  list row (trial / tracking / redirect / promo / segment) deleted through the
 *  same confirm→mutate→disabled-while-pending shape; this is that shape, once. */
export function ConfirmDeleteButton({
  confirm, onConfirm, pending, label = "Delete",
}: {
  confirm: string;
  onConfirm: () => void;
  pending?: boolean;
  label?: string;
}) {
  return (
    <Button
      size="sm" variant="danger" disabled={pending}
      onClick={() => { if (window.confirm(confirm)) onConfirm(); }}
    >
      {label}
    </Button>
  );
}

/** Copy-to-clipboard button that flashes "Copied". Tracking links passes the
 *  bundle's "Link copied" held 5 s; a click during the flash copies nothing. */
export function CopyButton({
  text, label = "Copy", doneLabel = "✓ Copied", holdMs = 1200,
}: { text: string; label?: string; doneLabel?: string; holdMs?: number }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm" variant="ghost"
      onClick={async () => {
        if (done) return;
        try {
          await navigator.clipboard?.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), holdMs);
        } catch { /* clipboard blocked */ }
      }}
      title={text}
    >
      {done ? doneLabel : label}
    </Button>
  );
}
