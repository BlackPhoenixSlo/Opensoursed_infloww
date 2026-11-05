"use client";

import { Check, X } from "lucide-react";

import { IfButton } from "@/components/ui/infloww";

import { fanOutNote, summarizeFanOut, type FanOutProgress, type FanOutResult } from "./fanOut";

/** The all-models fan-out's per-model outcomes; while the content is locked
 *  (compose/fanOut `fanOutLocked`), the lock note and Start over (off while a
 *  send is in flight: compose/fanOut `discardResults`). */
export function FanOutResults({
  results, noun, locked, busy, onStartOver,
}: {
  results: FanOutResult[];
  /** What was sent: "post", "broadcast". */
  noun: string;
  locked: boolean;
  /** A send in flight. */
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
            Content locked: a retry sends this same {noun} to the failed models only. Start over
            unlocks it, but the next send then goes to every included model again.
          </span>
          <IfButton onClick={onStartOver} disabled={busy}>Start over</IfButton>
        </div>
      )}
    </div>
  );
}

/** The footer's status line: the round in flight ("Sending to k / N…"), else
 *  why the button is off (the form changed since any send error: it wins),
 *  else the last send's error, else the failures a retry still owes (all
 *  rounds). A visible line, not the button's title: a phone has no hover. */
export function FanOutStatus({
  progress, verb, invalid, error, results,
}: {
  progress: FanOutProgress | null;
  /** "Posting", "Sending". */
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
