"use client";

/**
 * CustomsTab — the owed-customs queue, rendered as a tab of /messages ("Stuff").
 *
 * A fan tips for a custom and gets back a VOICE NOTE made for him — audio,
 * only ever audio. Orders are TRACKED from $50 (stacked tips count as one
 * order); the price the chatter QUOTES stays in the $100-$200 band.
 * Fulfilment is MANUAL, so this tab is the work list: who paid, how much,
 * how long ago, and a button that says it went out.
 *
 * WHY IT IS A TAB AND NOT ITS OWN NAV ENTRY
 * The queue is money already taken against work not yet done — it belongs
 * beside the other money surfaces (PPV, Tips), not as a tenth item competing
 * with them in the nav strip. `/customs` still resolves: the route redirects
 * to `?tab=customs`, so every link the manual, the settings copy and the help
 * bot already print keeps landing here.
 *
 * THE TAB HOLDS NO STATE. "Owed" is the
 * column `fans.customs_owed_at` (see automations/_customs). This is the
 * ONLY operator surface for it: the marker used to live on the fan's OnlyFans
 * nickname, but that field is rewritten from structured facts by the chat engines
 * on every tick, so it was erased about a minute after it was written. Clearing
 * here blanks the column and stamps it settled; `customs_watch` clears it too
 * when it sees the voice note go out.
 *
 * Cross-account by default, and deliberately ignores the page's date range:
 * the queue exists so nobody has to remember to look, and a debt does not stop
 * being owed because it fell out of a 30-day window.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import Link from "next/link";

import { relay } from "@/lib/relay";
import { fmtCents, fmtPrice } from "@/lib/format";

import CustomsPane from "./CustomsPane";
import {
  customsPaneReducer, fanKey, handoffText, initialCustomsPane, initialReopenLedger, isFailed,
  mayReopen, pullTicket, reopenLedger, rowKey,
  type Brief, type ContextMsg, type Failed, type OrderLines, type Pane, type PaneRow,
} from "./customsPaneReducer";

/** An account taking custom-sized tips with no watcher on it. */
interface UntrackedRow {
  account_id: string;
  account_name: string;
  qualifying_tips: number;
  biggest_cents: number;
}

interface CustomRow extends PaneRow {
  /** How many SEPARATE orders make up `tip_cents`. Two $100 tips a day apart
   *  are two voice notes, and the queue used to show one. 0 on a row whose
   *  amount could not be reconstructed from transactions. */
  order_count?: number;
  lifetime_spend_cents: number;
  chat_href: string;
}

function money(cents: number | null | undefined): string {
  if (cents == null) return "—";
  return fmtCents(cents);
}

/** How long he has been waiting. The number that should make someone move. */
function waited(iso: string | null): { label: string; hours: number } {
  if (!iso) return { label: "unknown", hours: 0 };
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms) || ms < 0) return { label: "unknown", hours: 0 };
  const h = ms / 3_600_000;
  if (h < 1) return { label: `${Math.round(h * 60)}m`, hours: h };
  if (h < 48) return { label: `${Math.round(h)}h`, hours: h };
  return { label: `${Math.round(h / 24)}d`, hours: h };
}

/** GET a pane lookup; a failure is the `{ error }` stored in its field, so
 *  this never rejects. */
async function lookup<T>(path: string, q: URLSearchParams): Promise<T | Failed> {
  try {
    return await relay.get<T>(`${path}?${q}`);
  } catch (e) {
    return { error: e instanceof Error ? e.message : "lookup failed" };
  }
}

/** A clear in flight: the row clicked (its "…") and its fan (`fanKey`) — the
 *  backend settles the fan, so Read / Pull go off on EVERY row of his. */
interface Busy {
  key: string;
  fan: string;
}

function Section({
  title,
  note,
  rows,
  busy,
  onClear,
}: {
  title: string;
  note: string;
  rows: CustomRow[];
  busy: Busy | null;
  /** POST the clear; resolves false if it failed (the row stays listed). */
  onClear: (r: CustomRow) => Promise<boolean>;
}) {
  const isReview = rows.length > 0 && !rows[0].marked;
  // Which row is expanded, and its thread. ONE at a time: this is a read-to-
  // decide surface, and two open threads is two things to hold in your head.
  // The pane's state — the open row's thread, brief and order span, and the
  // Pull / Copy button states — is one reducer (customsPaneReducer): every
  // reply carries the `seq` of the open it was asked for and is dropped once a
  // newer open (another row, the same row reopened, or Pull) has replaced it,
  // so a slow reply can never render in a pane it was not asked for.
  //   pane — `null` = nothing open; inside it a `null` ctx / brief / order =
  //     that request in flight. The order span loads WITH the row, not on a
  //     second click: it is the answer to "what do I record", so making the
  //     operator ask for it separately is the extra step he objected to. So
  //     does the brief. `pane.copied` — the last copy and whether it worked. A
  //     copy that silently succeeds is indistinguishable from one that
  //     silently failed, and the operator only finds out when he pastes an
  //     empty handoff.
  //   pulls — which rows are mid-pull, or failed. The re-scrape is synchronous
  //     (~1-2s) and the pane must not look merely slow while it runs.
  const [state, dispatch] = useReducer(customsPaneReducer, initialCustomsPane);
  const { pane, pulls } = state;
  /** Pull's reopen ledger — the rule is `mayReopen` (customsPaneReducer). A
   *  ref, not reducer state: a Pull reads it after its await, when the render
   *  it closed over is stale. */
  const ledger = useRef(initialReopenLedger);
  /** Bumped once per copy, so an older copy's timer can't clear a newer note. */
  const copySeq = useRef(0);

  /** Ask the model for this row's brief at tip time `at`, for the open `seq`.
   *  Best-effort: a failure is stored as a failed brief (the pane offers a
   *  retry). `at` is the pane's, not the row's: a Refresh may have moved the
   *  row's `tipped_at` since, and the brief must read the span the pane did. */
  const fetchBrief = useCallback(async (r: CustomRow, seq: number, at: string | null) => {
    try {
      const res = await relay.post<Brief>("/admin/customs/brief", {
        account_id: r.account_id,
        fan_id: r.fan_id,
        at,
      });
      dispatch({ type: "brief", seq, brief: res });
    } catch (e) {
      dispatch({
        type: "brief",
        seq,
        brief: { ok: false, reason: e instanceof Error ? e.message : "failed" },
      });
    }
  }, []);

  /** Open this row's pane: the thread around its anchor tip, its order span
   *  and its brief, all three requested in parallel. Each request catches its
   *  own failure and records it in the pane, so this never rejects; it
   *  resolves once all three have settled (which is what Pull's spinner
   *  waits for). */
  const openRow = useCallback(async (r: CustomRow) => {
    ledger.current = reopenLedger(ledger.current, { type: "paneMoved" });
    const seq = ledger.current.seq;
    const at = r.tipped_at;
    dispatch({ type: "open", key: rowKey(r), fan: fanKey(r), seq, at });
    const fan = { account_id: r.account_id, fan_id: String(r.fan_id) };
    const orderPull = (async () => {
      const res = await lookup<OrderLines>("/admin/customs/order", new URLSearchParams(fan));
      dispatch({ type: "order", seq, order: res });
    })();
    const briefPull = fetchBrief(r, seq, at);
    const ctxPull = (async () => {
      const q = new URLSearchParams({
        ...fan,
        // The endpoint accepts up to 60 either side and we were sending
        // neither, so every Read silently took the 18-before default. A fan
        // with two orders on different days needs to reach back past the
        // newer tip to the conversation that placed the older one.
        before: "50",
        after: "10",
      });
      if (at) q.set("at", at);
      const res = await lookup<{ messages: ContextMsg[] }>("/admin/customs/context", q);
      dispatch({ type: "ctx", seq, ctx: isFailed(res) ? res : res.messages || [] });
    })();
    await Promise.all([orderPull, briefPull, ctxPull]);
  }, [fetchBrief]);

  const toggle = useCallback(
    (r: CustomRow) => {
      if (pane?.key === rowKey(r)) {
        ledger.current = reopenLedger(ledger.current, { type: "paneMoved" });
        dispatch({ type: "close" });
        return;
      }
      void openRow(r);
    },
    [pane?.key, openRow],
  );

  /** Re-ask the model. The brief loads with the row (see `openRow`); this is
   *  the retry for when it failed or came back without the request. Per row,
   *  never per queue load — rows nobody opens cost nothing. `p` is the
   *  rendered pane: its `seq`, so a reopen / Pull / other row before it
   *  answers drops it, and its `at`, so the retry reads the same span. */
  const askBrief = useCallback(
    (r: CustomRow, p: Pane) => {
      dispatch({ type: "briefRetry", seq: p.seq });
      void fetchBrief(r, p.seq, p.at);
    },
    [fetchBrief],
  );

  /** Put the three-line handoff on the clipboard — see `handoffText`.
   *
   *  It copies what the rendered pane `p` has ALREADY loaded, which is why it
   *  lives inside the expanded row; the button is disabled until `canCopy(p)`
   *  (brief and order settled). The result carries `p.seq`, so a write that
   *  settles after its pane was replaced (even by a reopen of the same row)
   *  notes nothing in the new one. `writeText` rejects outside a secure
   *  context, so a failure has to be visible rather than leaving the operator
   *  to paste whatever was on the clipboard before. */
  const copyHandoff = useCallback(async (r: CustomRow, p: Pane) => {
    const n = ++copySeq.current;
    try {
      await navigator.clipboard.writeText(handoffText(r, p));
      dispatch({ type: "copyDone", seq: p.seq, n, ok: true });
      setTimeout(() => dispatch({ type: "copyExpired", n }), 2000);
    } catch {
      dispatch({ type: "copyDone", seq: p.seq, n, ok: false });
    }
  }, []);

  /** Re-scrape this fan's thread from OF, then re-open the pane.
   *
   *  The context pane can only show what we have STORED, so on a thread the
   *  scraper never reached the work order simply is not there. This is the
   *  existing chat ↻ endpoint (`rescrape-now`) — synchronous, ~1-2s, and
   *  best-effort: it answers ok=false rather than throwing. A failed pull
   *  leaves the pane exactly as it was (no re-read, no second paid brief) and
   *  says so on the row. An ok pull reopens the row only if `mayReopen`. */
  const pull = useCallback(
    async (r: CustomRow) => {
      const key = rowKey(r);
      const ticket = pullTicket(ledger.current, fanKey(r));
      dispatch({ type: "pullStart", key });
      let error: string | undefined;
      try {
        const res = await relay.post<{ ok: boolean; error?: string }>(
          `/admin/messages/${r.account_id}/${r.fan_id}/rescrape-now`,
          {},
        );
        if (!res.ok) error = res.error || "pull failed";
        else if (mayReopen(ledger.current, ticket)) await openRow(r);
      } catch (e) {
        error = e instanceof Error ? e.message : "pull failed";
      }
      dispatch({ type: "pullDone", key, error });
    },
    [openRow],
  );

  /** Sent / Dismiss: the backend settles the whole FAN (every row of his).
   *  His running Pulls lose their reopen at the click (see `mayReopen`). His
   *  open pane closes only once the POST succeeded: a failed clear leaves the
   *  row listed and the pane as it was (re-reading it would pay for a second
   *  brief). */
  const clear = useCallback(
    async (r: CustomRow) => {
      const fan = fanKey(r);
      ledger.current = reopenLedger(ledger.current, { type: "cleared", fan });
      if (!(await onClear(r))) return;
      dispatch({ type: "cleared", fan });
    },
    [onClear],
  );

  return (
    <section className="mb-8">
      <h2 className="mb-2 text-sm font-semibold">
        {title} <span className="ml-1 font-normal opacity-60">{note}</span>
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-left opacity-60">
              {/* The owed mark. It lives in fans.customs_owed_at now, so this
                  column IS the ledger made visible — there is no longer a copy of
                  it on OnlyFans to cross-check against. */}
              <th className="w-6 py-2 pr-2 font-medium" aria-label="Owed" />
              <th className="py-2 pr-3 font-medium">
                {isReview ? "Tipped" : "Waiting"}
              </th>
              <th className="py-2 pr-3 font-medium">Fan</th>
              <th className="py-2 pr-3 font-medium">Model</th>
              <th className="py-2 pr-3 font-medium">Paid</th>
              <th className="py-2 pr-3 font-medium">Lifetime</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {rows.flatMap((r) => {
              const w = waited(r.tipped_at);
              const key = rowKey(r);
              // The open row's pane, or null — so below, `p` is this row's.
              const p = pane?.key === key ? pane : null;
              const pullState = pulls[key];
              const isPulling = pullState === "running";
              // His clear is in flight (any row of his): he is leaving the
              // queue, so Read / Pull would pay for a brief on a settled fan.
              const fanBusy = busy?.fan === fanKey(r);
              const cells = (
                <tr key={key} className="border-b last:border-0">
                  {/* ✓ = tagged owed by customs_watch. ? = a qualifying tip that
                      nothing was watching for, which may equally be generosity —
                      so it gets a different glyph, not a quieter one. */}
                  <td
                    className="py-2 pr-2 text-center"
                    title={
                      isReview
                        ? "Qualifying tip, never tagged — check the thread"
                        : "Owed a custom"
                    }
                  >
                    <span
                      aria-hidden="true"
                      className={isReview ? "opacity-40" : "text-ok"}
                    >
                      {isReview ? "?" : "✓"}
                    </span>
                    <span className="sr-only">
                      {isReview ? "Needs review" : "Owed"}
                    </span>
                  </td>
                  {/* Two days of an UNPAID debt is a problem. Two days since a
                      tip nobody tagged is just a date. */}
                  <td
                    className={`py-2 pr-3 tabular-nums ${
                      !isReview && w.hours >= 48 ? "font-semibold text-err" : ""
                    }`}
                  >
                    {w.label}
                  </td>
                  <td className="py-2 pr-3">
                    {/* ?msg=<tip id> — the thread opens on the tip itself, the
                        message that has to be read to decide. */}
                    <Link
                      href={r.chat_href}
                      className="underline underline-offset-2 hover:opacity-70"
                    >
                      {r.display_name}
                    </Link>
                    {/* The handle, when it differs from what is already shown.
                        `display_name` falls back to the username, so printing
                        both unconditionally renders the same string twice. */}
                    {r.of_username && r.of_username !== r.display_name && (
                      <span className="ml-1 text-xs opacity-60">
                        @{r.of_username}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 opacity-80">{r.account_name}</td>
                  <td className="py-2 pr-3 tabular-nums font-medium">
                    {money(r.tip_cents)}
                    {/* TWO $100 tips a day apart are TWO voice notes. The total
                        alone reads as one big custom, so the count is what makes
                        it legible. Shown only when it is more than one — a "1"
                        on every row is noise. */}
                    {(r.order_count || 0) > 1 && (
                      <span
                        className="ml-1 font-normal opacity-60"
                        title={`${r.order_count} separate orders — ${r.order_count} voice notes owed`}
                      >
                        · {r.order_count} tips
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 tabular-nums opacity-70">
                    {money(r.lifetime_spend_cents)}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    {/* Read the thread WITHOUT leaving the page. The tip says a
                        man paid; the messages around it say what he paid FOR,
                        which is the whole decision on a review row. */}
                    <button
                      disabled={fanBusy}
                      onClick={() => toggle(r)}
                      className="mr-2 rounded border px-2 py-1 text-xs hover:bg-black/5 disabled:opacity-40"
                      title="Read the conversation around this tip"
                    >
                      {p ? "Hide" : "Read"}
                    </button>
                    {isFailed(pullState) && (
                      <span className="mr-2 text-xs text-err" title={pullState.error}>
                        Pull failed
                      </span>
                    )}
                    {/* When the stored thread is thin (or the work order sits
                        further back than we ever scraped), pull it from OF and
                        re-read. Same endpoint the chat ↻ uses. */}
                    <button
                      disabled={isPulling || fanBusy}
                      onClick={() => void pull(r)}
                      className="mr-2 rounded border px-2 py-1 text-xs hover:bg-black/5 disabled:opacity-40"
                      title="Re-fetch this chat from OnlyFans, then re-read it"
                    >
                      {isPulling ? "…" : "Pull"}
                    </button>
                    <button
                      disabled={fanBusy}
                      onClick={() => void clear(r)}
                      className="rounded border px-3 py-1 text-xs hover:bg-black/5 disabled:opacity-40"
                      title={
                        isReview
                          ? "Nothing owed here — settle it and stop showing it"
                          : (r.order_count || 0) > 1
                            // HONEST about the one thing this button cannot do.
                            // The ledger is a single nullable timestamp, so one
                            // click settles EVERY outstanding order for this fan
                            // — there is no way to say "I sent one of two", and
                            // customs_watch will not re-mark what is stamped
                            // cleared. Say so where the click happens.
                            ? `Mark delivered — settles ALL ${r.order_count} orders for this fan, not just one`
                            : "Mark delivered; also clears the Custom tag on OnlyFans"
                      }
                    >
                      {busy?.key === key ? "…" : isReview ? "Dismiss" : "Sent"}
                    </button>
                  </td>
                </tr>
              );
              if (!p) return [cells];
              return [
                cells,
                <CustomsPane
                  key={`${key}:ctx`}
                  row={r}
                  pane={p}
                  onReadAgain={() => void openRow(r)}
                  onCopy={() => void copyHandoff(r, p)}
                  onRetryBrief={() => askBrief(r, p)}
                />,
              ];
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function CustomsTab() {
  const [rows, setRows] = useState<CustomRow[] | null>(null);
  const [untracked, setUntracked] = useState<UntrackedRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await relay.get<{
        customs: CustomRow[];
        untracked?: UntrackedRow[];
      }>("/admin/customs");
      setRows(res.customs || []);
      setUntracked(res.untracked || []);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed to load");
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** POST the clear; true once it is settled (and dropped here), false if it
   *  failed (the error shows, the rows stay). */
  const clear = useCallback(
    async (r: CustomRow): Promise<boolean> => {
      setBusy({ key: rowKey(r), fan: fanKey(r) });
      try {
        await relay.post("/admin/customs/clear", {
          account_id: r.account_id,
          fan_id: r.fan_id,
        });
        // Drop it locally rather than refetching — the row is gone either way,
        // and an operator working a list of ten should not watch it flicker.
        setRows((prev) =>
          (prev || []).filter(
            (x) => !(x.account_id === r.account_id && x.fan_id === r.fan_id),
          ),
        );
        return true;
      } catch (e) {
        setErr(e instanceof Error ? e.message : "failed to clear");
        return false;
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const owed = (rows || []).filter((r) => r.marked);
  const review = (rows || []).filter((r) => !r.marked);
  const owedTotal = owed.reduce((n, r) => n + (r.tip_cents || 0), 0);

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Customs owed</h2>
          <p className="mt-1 text-sm opacity-70">
            Paid for, not yet sent. Every custom is a voice note. Clearing a row
            marks it delivered and stops the AI selling to him again &mdash; this
            page is the only place that happens.
          </p>
        </div>
        <button
          onClick={() => void load()}
          className="rounded border px-3 py-1.5 text-sm hover:bg-black/5"
        >
          Refresh
        </button>
      </header>

      {err && (
        <div className="mb-4 rounded border border-err/40 bg-err/10 px-3 py-2 text-sm">
          {err}
        </div>
      )}

      {/* The one hole in a per-account switch: an eligible account never gets
          the rule and nobody notices — which looks exactly like a healthy empty
          queue. Shown ABOVE the table, and on the empty state too. */}
      {untracked.length > 0 && (
        <div className="mb-5 rounded border border-warn/40 bg-warn/10 px-3 py-2 text-sm">
          <p className="font-medium">
            Not tracking customs on {untracked.length}{" "}
            {untracked.length === 1 ? "account" : "accounts"}
          </p>
          <p className="mt-1 opacity-80">
            These took tips big enough to be a custom order in the last 14 days,
            with no <code>customs_watch</code> automation enabled. If those tips
            were orders, nothing is recording them.
          </p>
          <ul className="mt-2 space-y-0.5">
            {untracked.map((u) => (
              <li key={u.account_id} className="tabular-nums">
                <span className="font-medium">{u.account_name}</span> —{" "}
                {u.qualifying_tips}{" "}
                {u.qualifying_tips === 1 ? "tip" : "tips"}, biggest{" "}
                {u.biggest_cents == null ? "—" : fmtPrice(u.biggest_cents)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {rows === null && <p className="text-sm opacity-60">Loading…</p>}

      {rows !== null && rows.length === 0 && !err && (
        <div className="rounded border border-dashed px-4 py-10 text-center">
          <p className="font-medium">Nothing owed.</p>
          <p className="mt-1 text-sm opacity-60">
            A qualifying tip adds a fan here automatically.
          </p>
        </div>
      )}

      {/* TWO LISTS, not one table with a flag. A marked row is DEBT — money
          taken, work owed, red past two days. An unmarked row is a QUESTION —
          a tip that may equally have been generosity. Sorting them into one
          oldest-first list buries a real 12-hour debt under a 50-day maybe,
          and the "Waiting" column means a different thing in each. */}
      {rows !== null && owed.length > 0 && (
        <Section
          title="Owed"
          note={`${owed.length} · ${money(owedTotal)} taken`}
          rows={owed}
          busy={busy}
          onClear={clear}
        />
      )}

      {rows !== null && review.length > 0 && (
        <Section
          title="Worth a look"
          note={`${review.length} · tips big enough to be an order, never tagged`}
          rows={review}
          busy={busy}
          onClear={clear}
        />
      )}

    </div>
  );
}
