"use client";

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
    <div className="border border-border rounded-md p-3 space-y-1 text-[11px]">
      <div className="font-medium">Fan-out results — {summarizeFanOut(results)}</div>
      {results.map((r) => (
        <div key={r.accountId} className={r.ok ? "text-ok" : "text-err"}>
          {r.ok ? "✓" : "✗"} {r.accountId}
          {r.error ? ` — ${r.error}` : ""}
        </div>
      ))}
      {locked && (
        <div className="flex items-center gap-2 pt-1 text-fg-dim">
          <span className="mr-auto">
            Content locked: a retry sends this same {noun} to the models without a ✓. Start over
            unlocks it, but the next send then goes to every included model again, the ✓ ones too.
          </span>
          <button
            type="button"
            onClick={onStartOver}
            disabled={busy}
            className="shrink-0 px-2 py-1 rounded border border-border hover:border-border-light hover:text-fg disabled:opacity-50"
          >
            Start over
          </button>
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
    return <span className="text-fg-dim text-[11px] mr-auto">{verb} to {progress.done} / {progress.total}…</span>;
  }
  const note = invalid ?? error ?? fanOutNote(results);
  if (!note) return null;
  return (
    <span role="status" className={`${invalid ? "text-fg-dim" : "text-err"} text-[11px] mr-auto`}>{note}</span>
  );
}
