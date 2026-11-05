"use client";

/**
 * FunnelLaunchPanel — "Start" a funnel from the Mass Funnels tab.
 *
 * Fires the funnel's OPENING message to a chosen audience via the same path the
 * Mass composer uses (POST /api/of/v2/messages/queue with `funnel_id`), so the
 * mass_run is funnel-linked and reply_mass_funnel walks the reply/PPV steps for
 * every fan who answers. The audience controls map 1:1 to the relay's queue body:
 *   include lists  → user_lists           exclude lists → excluded_user_lists
 *   Online only    → online_only          Skip recently-messaged → exclude_replied_hours
 * (exclude_replied_hours drops fans we sent an OUTBOUND message to in the last N
 *  hours — see service/audiences.resolve_mass_audience.)
 *
 * Real send: a confirm() gate guards the blast. price=0 (the opener is free; the
 * paid PPV lives in a later funnel step).
 */

import { useEffect, useReducer, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Play, X } from "lucide-react";

import { IfButton, IfHelp, IfInput, IfLabel, IfSwitch } from "@/components/ui/infloww";
import { SYSTEM_AUDIENCES, useFanLists } from "@/components/audience/fanLists";
import {
  MASS_EXCLUDE_LIST_NAME, audienceError, audienceReducer, buildAudiencePayload, initAudience, massExcludeListId,
} from "@/components/audience/audienceReducer";
import { relay } from "@/lib/relay";
import { useEmployee } from "@/contexts/EmployeeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import type { FunnelSummary } from "@/hooks/useFunnels";

// What a funnel opener sends to on open: all fans (Following is one click).
const OPENER_INCLUDES = ["fans"];
// Default auto-unsend window for a funnel opener (hours). Pre-fills the field.
const DEFAULT_UNSEND_HOURS = "4";

/** One account's panel: the caller keys it by `accountId` (list ids are per
 *  account), so a Creator switch mounts a fresh audience. */
export function FunnelLaunchPanel({
  funnel,
  accountId,
  onClose,
}: {
  funnel: FunnelSummary;
  accountId: string | null;
  onClose: () => void;
}) {
  const { current: currentEmployee } = useEmployee();
  const accounts = useActiveAccounts();
  const accountName = accounts.find((a) => a.id === accountId)?.nickname ?? accountId ?? "";

  const [aud, dispatch] = useReducer(audienceReducer, accountId, (id) => initAudience(id, OPENER_INCLUDES));
  const { includes, excludes } = aud;
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [skipMessagedHours, setSkipMessagedHours] = useState("");
  // Auto-unsend the opener N hours after it sends. When it's unsent we also STOP
  // enrolling NEW repliers off this mass (the walker keeps going until a buy).
  // Pre-filled with the default; blank → no per-send auto-unsend.
  const [unsendHours, setUnsendHours] = useState(DEFAULT_UNSEND_HOURS);
  const [done, setDone] = useState<string | null>(null);

  const { customLists, data: lists, isFetching } = useFanLists(accountId);

  // Default the standing MASSDMEXCLUDE list into the exclude set once the
  // account's lists settle (not a stale cache mid-refetch); seeded once, so the
  // operator's untick for a one-off sticks.
  useEffect(() => {
    if (!accountId || !lists || isFetching) return;
    dispatch({ type: "seedExclude", accountId, listId: massExcludeListId(lists) });
  }, [accountId, lists, isFetching]);

  // Start waits for that seed, so the opener never goes out before MASSDMEXCLUDE
  // is excluded (the copy below promises it).
  const seeded = aud.seededFor === accountId;

  // An audience can't be both included and excluded (audienceReducer).
  function toggle(side: "in" | "out", id: string) {
    setDone(null);
    dispatch({ type: side === "in" ? "toggleInclude" : "toggleExclude", id });
  }

  const send = useMutation({
    mutationFn: async () => {
      if (!accountId) throw new Error("Pick a model (account) above first");
      const audErr = audienceError(aud);
      if (audErr) throw new Error(audErr);
      const body: Record<string, unknown> = {
        text: funnel.opening_message,
        ...buildAudiencePayload(aud),
        user_ids: [],
        excluded_users: [],
        price: 0,
        locked_text: false,
        media_files: [],
        funnel_id: funnel.id,
      };
      if (onlineOnly) body.online_only = true;
      const h = Number(skipMessagedHours);
      if (skipMessagedHours.trim() !== "" && Number.isFinite(h) && h > 0) {
        body.exclude_replied_hours = h;
      }
      const uh = Number(unsendHours);
      if (unsendHours.trim() !== "" && Number.isFinite(uh) && uh > 0) {
        body.unsend_after_hours = uh;
      }
      return relay.post<{ _skipped_already_answered?: number }>(
        "/api/of/v2/messages/queue", body,
        { accountId, employeeId: currentEmployee?.id },
      );
    },
    onSuccess: (resp) => {
      const skipped = Number(resp?._skipped_already_answered) || 0;
      const base = "Funnel started — opener queued to OnlyFans. Replies will auto-walk the steps.";
      setDone(skipped > 0
        ? `${base} (${skipped} already answered this funnel — skipped.)`
        : base);
    },
  });

  function confirmAndSend() {
    setDone(null);
    const who = onlineOnly ? "ONLINE fans in" : "fans in";
    const ok = window.confirm(
      `Send "${funnel.name}" opener to ${who} the selected audience on ${accountName}?`,
    );
    if (ok) send.mutate();
  }

  const ChipRow = ({
    items, side,
  }: {
    items: Array<{ id: string; label: string }>;
    side: "in" | "out";
  }) => (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it) => {
        const on = (side === "in" ? includes : excludes).has(it.id);
        return (
          <button
            key={it.id}
            type="button"
            aria-pressed={on}
            onClick={() => toggle(side, it.id)}
            className={
              "px-2.5 py-1 rounded-full text-xs border transition-colors " +
              (on
                ? "border-accent bg-accent/15 text-fg"
                : "border-border text-fg-dim hover:text-fg")
            }
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );

  const listItems = customLists.map((l) => ({ id: String(l.id), label: l.name ?? `List ${l.id}` }));

  return (
    <div className="space-y-4 rounded-md border border-border bg-panel p-4">
      <header className="flex items-center justify-between gap-2">
        <h3 className="min-w-0 truncate text-[14px] font-medium text-fg">Start funnel · {funnel.name}</h3>
        <IfButton variant="link" icon={X} aria-label="Close" onClick={onClose} className="w-8 text-muted hover:text-fg" />
      </header>

      <div>
        <IfLabel>Opening message</IfLabel>
        <div className="whitespace-pre-wrap rounded-md border border-border bg-bg px-[11px] py-1 text-[14px] text-fg">
          {funnel.opening_message}
        </div>
        <IfHelp>Sent now; fans who answer are auto-walked through the steps.</IfHelp>
      </div>

      {!accountId && (
        <div className="text-[12px] text-warn">Pick a model (account) in the chips above first.</div>
      )}

      {/* Include */}
      <div>
        <IfLabel>Send to (include)</IfLabel>
        <div className="space-y-1.5">
          <ChipRow items={SYSTEM_AUDIENCES} side="in" />
          {listItems.length > 0 && (
            <ChipRow items={listItems} side="in" />
          )}
        </div>
      </div>

      {/* Exclude: custom lists only — OF silently drops built-in names in
          excludedLists (fanLists.tsx), so an "All fans" exclude would over-send. */}
      {listItems.length > 0 && (
        <div>
          <IfLabel>Exclude</IfLabel>
          <ChipRow items={listItems} side="out" />
          <IfHelp>{MASS_EXCLUDE_LIST_NAME} is excluded by default; fans who already answered are skipped.</IfHelp>
        </div>
      )}

      <IfSwitch label="Online only" checked={onlineOnly} onChange={(on) => { setDone(null); setOnlineOnly(on); }}
        className="flex" />

      {/* Skip-recent + auto-unsend */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <IfLabel htmlFor={`funnel-${funnel.id}-skip`}>Skip fans I messaged in the last … hours</IfLabel>
          <IfInput
            id={`funnel-${funnel.id}-skip`}
            type="number"
            min={0}
            className="w-28"
            placeholder="e.g. 2"
            value={skipMessagedHours}
            onChange={(e) => { setDone(null); setSkipMessagedHours(e.target.value); }}
          />
          <IfHelp>blank = skip no one</IfHelp>
        </div>
        <div>
          <IfLabel htmlFor={`funnel-${funnel.id}-unsend`}>Auto-unsend opener after … hours</IfLabel>
          <IfInput
            id={`funnel-${funnel.id}-unsend`}
            type="number"
            min={0}
            className="w-28"
            placeholder="e.g. 4"
            value={unsendHours}
            onChange={(e) => { setDone(null); setUnsendHours(e.target.value); }}
          />
          <IfHelp>Unsent: new repliers stop enrolling; open chats keep going.</IfHelp>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <IfButton variant="primary" icon={send.isPending ? undefined : Play} onClick={confirmAndSend}
          disabled={send.isPending || !accountId || !seeded}>
          {send.isPending ? "Sending…" : "Start funnel"}
        </IfButton>
        {done && <span className="text-[12px] text-ok">{done}</span>}
        {send.isError && (
          <span className="text-[12px] text-err">{(send.error as Error)?.message || "Send failed"}</span>
        )}
      </div>
    </div>
  );
}
