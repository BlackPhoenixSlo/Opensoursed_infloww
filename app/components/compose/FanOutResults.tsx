"use client";

import { Check, X } from "lucide-react";

import { IfButton } from "@/components/ui/infloww";

import { fanOutNote, summarizeFanOut, type FanOutProgress, type FanOutResult } from "./fanOut";

export function FanOutResults({
  results, noun, locked, busy, onStartOver,
}: {
  results: FanOutResult[];
  noun: string;
  locked: boolean;
  busy: boolean;
  onStartOver: () => void;
}) {
  return (
    <div className="space-y-1 rounded-md border border-border p-3 text-[12px]">
      <div className="text-[14px] font-medium">Fan-out results — {summarizeFanOut(results)}</div>
      {results.map((r) => (
        <div key={r.accountId} className={`flex items-center gap-1.5 ${r.ok ? "text-ok" : "text-err"}`}>
          {r.ok ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden /> : <X className="h-3.5 w-3.5 shrink-0" aria-hidden />}
          {r.accountId}
          {r.error ? ` — ${r.error}` : ""}
        </div>
      ))}
      {locked && (
        <div className="flex flex-wrap items-center gap-2 pt-1 text-fg-dim">
          <span className="min-w-0 flex-1">
            Content locked: a retry sends this same {noun} to every included model without a ✓. Start over
            unlocks it, but the next send then goes to every included model again, the ✓ ones too.
          </span>
          <IfButton onClick={onStartOver} disabled={busy}>Start over</IfButton>
        </div>
      )}
    </div>
  );
}

export function FanOutStatus({
  progress, verb, invalid, error, results,
}: {
  progress: FanOutProgress | null;
  verb: string;
  invalid: string | null;
  error: string | null;
  results: FanOutResult[] | null;
}) {
  if (progress) {
    return <span className="mr-auto text-[12px] max-sm:basis-full text-fg-dim">{verb} to {progress.done} / {progress.total}…</span>;
  }
  const note = invalid ?? error ?? fanOutNote(results);
  if (!note) return null;
  return (
    <span role="status" className={`${invalid ? "text-fg-dim" : "text-err"} mr-auto text-[12px] max-sm:basis-full`}>{note}</span>
  );
}
