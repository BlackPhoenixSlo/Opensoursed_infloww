"use client";


import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import Link from "next/link";

import { relay } from "@/lib/relay";
import { fmtCents as money, fmtPrice } from "@/lib/format";

import CustomsPane from "./CustomsPane";
import {
  customsPaneReducer, fanKey, handoffText, initialCustomsPane, initialReopenLedger, isFailed,
  mayReopen, pullTicket, reopenLedger, rowKey,
  type Brief, type ContextMsg, type Failed, type OrderLines, type Pane, type PaneRow, type PullNotice,
} from "./customsPaneReducer";

interface UntrackedRow {
  account_id: string;
  account_name: string;
  qualifying_tips: number;
  biggest_cents: number;
}

interface CustomRow extends PaneRow {
  order_count?: number;
  lifetime_spend_cents: number;
  chat_href: string;
}

function waited(iso: string | null): { label: string; hours: number } {
  if (!iso) return { label: "unknown", hours: 0 };
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms) || ms < 0) return { label: "unknown", hours: 0 };
  const h = ms / 3_600_000;
  if (h < 1) return { label: `${Math.round(h * 60)}m`, hours: h };
  if (h < 48) return { label: `${Math.round(h)}h`, hours: h };
  return { label: `${Math.round(h / 24)}d`, hours: h };
}

async function lookup<T>(path: string, q: URLSearchParams): Promise<T | Failed> {
  try {
    return await relay.get<T>(`${path}?${q}`);
  } catch (e) {
    return { error: e instanceof Error ? e.message : "lookup failed" };
  }
}

interface Busy {
  key: string;
  fan: string;
}

// Owed lives in fans.customs_owed_at: the OF-nickname marker was rewritten by the chat engines within a minute. One clear settles every order of the fan.
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
  onClear: (r: CustomRow) => Promise<boolean>;
}) {
  const isReview = rows.length > 0 && !rows[0].marked;
  const [state, dispatch] = useReducer(customsPaneReducer, initialCustomsPane);
  const { pane, pulls } = state;
  const ledger = useRef(initialReopenLedger);
  const copySeq = useRef(0);

  const fetchBrief = useCallback(async (r: CustomRow, seq: number, at: string | null) => {
    try {
      const res = await relay.post<Brief>("/admin/customs/brief", {
        account_id: r.account_id,
        fan_id: r.fan_id,
        at,
      }, { cellAccountId: r.account_id });
      dispatch({ type: "brief", seq, brief: res });
    } catch (e) {
      dispatch({
        type: "brief",
        seq,
        brief: { ok: false, reason: e instanceof Error ? e.message : "failed" },
      });
    }
  }, []);

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
        // The endpoint takes up to 60 either side; its 18-before default misses the conversation that placed an older order.
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

  const askBrief = useCallback(
    (r: CustomRow, p: Pane) => {
      dispatch({ type: "briefRetry", seq: p.seq });
      void fetchBrief(r, p.seq, p.at);
    },
    [fetchBrief],
  );

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

  const pull = useCallback(
    async (r: CustomRow) => {
      const key = rowKey(r);
      const ticket = pullTicket(ledger.current, fanKey(r));
      dispatch({ type: "pullStart", key });
      let error: string | undefined;
      let notice: PullNotice | undefined;
      try {
        const res = await relay.post<{ status: "complete" | PullNotice; error?: string }>(
          `/admin/messages/${r.account_id}/${r.fan_id}/rescrape-now`,
          {},
        );
        if (res.status === "complete") {
          if (mayReopen(ledger.current, ticket)) await openRow(r);
        } else {
          error = res.error;
          notice = res.status;
        }
      } catch (e) {
        error = e instanceof Error ? e.message : "pull failed";
      }
      dispatch({ type: "pullDone", key, error, notice });
    },
    [openRow],
  );

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
              const p = pane?.key === key ? pane : null;
              const pullState = pulls[key];
              const isPulling = pullState === "running";
              const fanBusy = busy?.fan === fanKey(r);
              const cells = (
                <tr key={key} className="border-b last:border-0">
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
                  <td
                    className={`py-2 pr-3 tabular-nums ${
                      !isReview && w.hours >= 48 ? "font-semibold text-err" : ""
                    }`}
                  >
                    {w.label}
                  </td>
                  <td className="py-2 pr-3">
                    <Link
                      href={r.chat_href}
                      className="underline underline-offset-2 hover:opacity-70"
                    >
                      {r.display_name}
                    </Link>
                    {r.of_username && r.of_username !== r.display_name && (
                      <span className="ml-1 text-xs opacity-60">
                        @{r.of_username}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 opacity-80">{r.account_name}</td>
                  <td className="py-2 pr-3 tabular-nums font-medium">
                    {money(r.tip_cents)}
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
                    <button
                      disabled={fanBusy}
                      onClick={() => toggle(r)}
                      className="mr-2 rounded border px-2 py-1 text-xs hover:bg-black/5 disabled:opacity-40"
                      title="Read the conversation around this tip"
                    >
                      {p ? "Hide" : "Read"}
                    </button>
                    {(pullState === "partial" || pullState === "pending") && (
                      <span className="mr-2 text-xs">
                        {pullState === "partial" ? "History incomplete" : "Pull still running"}
                      </span>
                    )}
                    {isFailed(pullState) && (
                      <span className="mr-2 text-xs text-err" title={pullState.error}>
                        Pull failed
                      </span>
                    )}
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

// Deliberately cross-account and outside the page's date range: a debt stays owed whatever the window.
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

  const clear = useCallback(
    async (r: CustomRow): Promise<boolean> => {
      setBusy({ key: rowKey(r), fan: fanKey(r) });
      try {
        await relay.post("/admin/customs/clear", {
          account_id: r.account_id,
          fan_id: r.fan_id,
        }, { cellAccountId: r.account_id });
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
