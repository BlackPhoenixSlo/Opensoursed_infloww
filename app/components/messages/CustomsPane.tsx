"use client";

/**
 * CustomsPane — the expanded row of CustomsTab's Section: the open row's
 * handoff bar, order span, brief and thread, as `customsPaneReducer`'s `Pane`
 * holds them. Render only: the Section owns the reducer, the requests and the
 * refs, and hands in what each button does.
 */

import { fmtPrice } from "@/lib/format";

import {
  briefPhase, canCopy, isFailed, loaded, speaker,
  type ContextMsg, type Pane, type PaneRow,
} from "./customsPaneReducer";

/** The fan's own words, most likely to BE the work order.
 *
 *  His longest inbound message in the pane. No model, no inference, no
 *  paraphrase — a summary that quietly rewrites "25 back 25 front" is worse
 *  than no summary at all, because the operator films against it. This is
 *  verbatim or nothing, and when it guesses wrong the raw thread is directly
 *  underneath it.
 *
 *  Tip rows carry no body of their own (the money is the content), so they are
 *  skipped; very short replies ("ok", "yes") never carry a brief. */
function workOrderQuote(msgs: ContextMsg[]): string | null {
  let best: string | null = null;
  for (const m of msgs) {
    if (!m.from_fan || m.is_tip) continue;
    const t = (m.text || "").trim();
    if (t.length < 25) continue;
    if (best === null || t.length > best.length) best = t;
  }
  return best;
}

export default function CustomsPane({
  row,
  pane,
  onReadAgain,
  onCopy,
  onRetryBrief,
}: {
  /** The row as listed now (its `tipped_at` may have moved since `pane.at`). */
  row: PaneRow;
  /** This row's open pane. */
  pane: Pane;
  /** Re-open the row at its current tip ("read again"). */
  onReadAgain: () => void;
  /** Copy the handoff from what `pane` has loaded. */
  onCopy: () => void;
  /** Re-ask the brief for `pane` (same open, same `pane.at`). */
  onRetryBrief: () => void;
}) {
  const phase = briefPhase(pane.brief);
  const { ctx, brief, order, copied } = pane;
  const msgs = loaded(ctx), span = loaded(order);
  const quote = msgs === null ? null : workOrderQuote(msgs);
  return (
    <tr className="border-b last:border-0">
      <td colSpan={7} className="bg-black/[0.03] px-3 py-3">
        {ctx === null && (
          <p className="text-xs opacity-60">Reading…</p>
        )}
        {isFailed(ctx) && (
          <p className="text-xs text-err">
            Couldn&rsquo;t load the thread ({ctx.error}).
          </p>
        )}
        {msgs !== null && msgs.length === 0 && (
          <p className="text-xs opacity-60">
            No messages stored around this tip.
          </p>
        )}
        {/* He tipped again since this pane was read: the brief and
            thread are the old tip's, the total is the new one. */}
        {pane.at !== row.tipped_at && (
          <p className="mb-2 text-xs text-warn">
            He tipped again since this was read &mdash;{" "}
            <button
              onClick={onReadAgain}
              className="underline underline-offset-2 hover:opacity-70"
            >
              read again
            </button>
          </p>
        )}
        {/* THE HANDOFF, first and above the model brief, because
            this is what actually gets sent on: username, account,
            his words. The brief below is the optional read-it-for-me
            layer — it was the ONLY layer, which is the "too
            complicated" the operator named. The bar is drawn with
            the pane; only Copy waits on `canCopy`, NOT on the
            thread: the handoff is brief + order, and "order lookup
            failed" must show while the thread still loads. */}
        <div className="mb-3 flex items-center gap-2">
          <button
            onClick={onCopy}
            disabled={!canCopy(pane)}
            className="rounded border px-2 py-1 text-xs hover:bg-black/5 disabled:opacity-40"
            title={
              canCopy(pane)
                ? "Copy username, account and his exact words"
                : "Waiting for the order and the summary…"
            }
          >
            Copy handoff
          </button>
          {copied?.ok && (
            <span className="text-xs text-ok">Copied</span>
          )}
          {copied && !copied.ok && (
            <span className="text-xs text-err">
              Copy blocked &mdash; select the text below instead
            </span>
          )}
          {isFailed(order) && (
            <span className="text-xs text-err">
              order lookup failed ({order.error})
            </span>
          )}
          {span && span.lines.length === 0 && (
            <span className="text-xs opacity-60">
              {span.reason || "no order talk found in this thread"}
            </span>
          )}
          {!row.of_username && (
            // The one case the handoff cannot fill in. Say it
            // where the copy happens, not after it is pasted.
            <span className="text-xs opacity-60">
              no @username stored &mdash; try &ldquo;Pull&rdquo;
            </span>
          )}
        </div>
        {/* THE ORDER — the same lines the copy button falls back to
            when there is no brief (same `speaker`). Rendered ABOVE the raw thread because it IS the answer:
            the thread below is a window around the money, and on a
            layaway custom the money is months from the ask. */}
        {span && span.lines.length > 0 && (
          <div className="mb-3 rounded border border-ok/40 bg-ok/5 px-3 py-2">
            <p className="text-xs font-semibold">
              The order
              {span.opened_at && (
                <span className="ml-1 font-normal opacity-70">
                  · since {span.opened_at.slice(0, 10)}
                </span>
              )}
            </p>
            <div className="mt-1 space-y-1">
              {span.lines.map((m) => (
                <div key={m.message_id} className="flex gap-2 text-xs">
                  <span
                    className={`w-8 shrink-0 font-medium ${
                      m.is_tip
                        ? ""
                        : m.from_fan
                          ? "text-ok"
                          : "opacity-50"
                    }`}
                  >
                    {speaker(m)}
                  </span>
                  <span className="w-16 shrink-0 opacity-50">
                    {(m.at || "").slice(0, 10)}
                  </span>
                  <span className="min-w-0">{m.text}</span>
                </div>
              ))}
            </div>
            {span.truncated && (
              // Never let an EDIT look like the whole thread.
              <p className="mt-1 text-[11px] opacity-50">
                Long thread &mdash; showing only the lines that
                mention the order.
              </p>
            )}
          </div>
        )}
        {/* WHAT TO DO. Loads with the row — this is the handoff
            body, so it is never behind a second click. */}
        <div className="mb-3">
          {phase === "loading" && (
            <p className="text-xs opacity-60">Reading the thread…</p>
          )}
          {phase === "failed" && (
            <p className="text-xs opacity-60">
              Couldn&rsquo;t summarise
              {brief?.reason ? ` (${brief.reason})` : ""} &mdash;{" "}
              <button
                onClick={onRetryBrief}
                className="underline underline-offset-2 hover:opacity-70"
              >
                try again
              </button>
              . The copy button uses his raw lines meanwhile.
            </p>
          )}
          {phase === "not-found" && brief && (
            <div className="rounded border border-warn/40 bg-warn/10 px-3 py-2">
              <p className="text-xs font-semibold">
                His ask isn&rsquo;t in this excerpt
              </p>
              <p className="mt-1 text-xs opacity-80">
                {brief.summary ||
                  "He never says what he wants in the messages we have."}{" "}
                Try &ldquo;Pull&rdquo; to fetch more of the thread from
                OnlyFans, or read it below.
              </p>
            </div>
          )}
          {phase === "ready" && brief && (
            <div className="rounded border border-ok/40 bg-ok/5 px-3 py-2">
              <p className="text-xs font-semibold">
                What to do
                {brief.call_him && (
                  <span className="ml-1 font-normal opacity-70">
                    · call him <strong>{brief.call_him}</strong>
                  </span>
                )}
              </p>
              {brief.summary && (
                <p className="mt-1 text-xs">{brief.summary}</p>
              )}
              {(brief.his_words || []).length > 0 && (
                <div className="mt-1.5 text-xs opacity-80">
                  <span className="font-medium">His words:</span>
                  {(brief.his_words || []).map((w, i) => (
                    <p key={i} className="italic">&ldquo;{w}&rdquo;</p>
                  ))}
                </div>
              )}
              <p className="mt-1 text-[11px] opacity-50">
                Generated from 100 messages either side of the tip.
                Check them below.
              </p>
            </div>
          )}
        </div>
        {quote && (
          <blockquote
            className="mb-3 border-l-2 border-ok/50 pl-3 text-xs italic opacity-90"
            title="His longest message here — verbatim, not summarised"
          >
            {quote}
          </blockquote>
        )}
        {msgs !== null && msgs.length > 0 && (
          <div className="space-y-1.5">
            {msgs.map((m) => (
              <div
                key={m.message_id}
                className={`flex gap-2 text-xs ${
                  m.from_fan ? "" : "opacity-70"
                }`}
              >
                <span className="w-10 shrink-0 font-medium">
                  {m.from_fan ? "fan" : "us"}
                </span>
                <span className="min-w-0">
                  {/* A tip row has no body — show the money, which
                      is the thing being explained. */}
                  {m.is_tip ? (
                    <em className="not-italic font-semibold">
                      💸 tipped{" "}
                      {m.text.match(/\$[\d,.]+/)?.[0] ?? ""}
                    </em>
                  ) : (
                    m.text || <span className="opacity-40">(media)</span>
                  )}
                  {m.price_cents > 0 && (
                    <span className="ml-1 opacity-60">
                      [{fmtPrice(m.price_cents)} locked]
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}
