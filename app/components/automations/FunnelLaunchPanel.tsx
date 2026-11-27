"use client";


import { useEffect, useReducer, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Play, X } from "lucide-react";

import { IfButton, IfHelp, IfInput, IfLabel, IfSwitch } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";
import { SYSTEM_AUDIENCES, useFanLists } from "@/components/audience/fanLists";
import {
  MASS_EXCLUDE_LIST_NAME, audienceError, audienceReducer, buildAudiencePayload, initAudience, massExcludeListId,
} from "@/components/audience/audienceReducer";
import { sendKey, withRetainedOp, type RetainedOps } from "@/lib/opId";
import { relay } from "@/lib/relay";
import { useEmployee } from "@/contexts/EmployeeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import type { FunnelSummary } from "@/hooks/useFunnels";
import { ifConfirm } from "@/components/ui/ifConfirm";

const OPENER_INCLUDES = ["fans"];
const DEFAULT_UNSEND_HOURS = "4";

export function FunnelLaunchPanel({
  funnel,
  accountId,
  followUpsOn,
  onClose,
}: {
  funnel: FunnelSummary;
  accountId: string | null;
  followUpsOn: boolean;
  onClose: () => void;
}) {
  const launchOp = useRef<RetainedOps | null>(null);
  const { current: currentEmployee } = useEmployee();
  const qc = useQueryClient();
  const accounts = useActiveAccounts();
  const accountName = accounts.find((a) => a.id === accountId)?.nickname ?? accountId ?? "";

  const [aud, dispatch] = useReducer(audienceReducer, accountId, (id) => initAudience(id, OPENER_INCLUDES));
  const { includes, excludes } = aud;
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [skipMessagedHours, setSkipMessagedHours] = useState("");
  // Once the opener is unsent, no NEW repliers are enrolled from this mass (the walker keeps going until a buy).
  const [unsendHours, setUnsendHours] = useState(DEFAULT_UNSEND_HOURS);
  const [more, setMore] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const { customLists, data: lists, isFetching } = useFanLists(accountId);

  // Seed MASSDMEXCLUDE once the lists settle (not a stale cache mid-refetch), so an operator's untick sticks.
  useEffect(() => {
    if (!accountId || !lists || isFetching) return;
    dispatch({ type: "seedExclude", accountId, listId: massExcludeListId(lists) });
  }, [accountId, lists, isFetching]);

  // Start waits for the seed so the opener never goes out before MASSDMEXCLUDE is excluded.
  const seeded = aud.seededFor === accountId;

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
      return withRetainedOp(launchOp, sendKey(accountId, body), (opId) =>
        relay.post<{ _skipped_already_answered?: number }>(
          "/api/of/v2/messages/queue", body, { accountId, employeeId: currentEmployee?.id, opId },
        ),
      );
    },
    onSuccess: (resp) => {
      const skipped = Number(resp?._skipped_already_answered) || 0;
      const base = "Funnel started — opener queued to OnlyFans. Follow-ups are on: replies walk the steps.";
      setDone(skipped > 0
        ? `${base} (${skipped} already answered this funnel — skipped.)`
        : base);
      void qc.invalidateQueries({ queryKey: ["automation-rules", accountId] });
      void qc.invalidateQueries({ queryKey: ["funnels"] });
    },
  });

  async function confirmAndSend() {
    setDone(null);
    const who = onlineOnly ? "ONLINE fans in" : "fans in";
    const ok = await ifConfirm(
      `Send "${funnel.name}" opener to ${who} the selected audience on ${accountName}?`
        + (followUpsOn ? "" : "\n\nThis also turns on Follow up on replies for this creator."),
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
            className={cn("h-7 rounded-full border px-3 text-[12px] transition-colors",
              on ? "border-accent bg-accent/15 text-fg" : "border-border text-fg-dim hover:text-fg")}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );

  const listItems = customLists.map((l) => ({ id: String(l.id), label: l.name ?? `List ${l.id}` }));
  const uh = Number(unsendHours);
  const moreSummary = [
    unsendHours.trim() !== "" && uh > 0 ? `auto-unsend after ${unsendHours} h` : "no auto-unsend",
    onlineOnly && "online only",
    skipMessagedHours.trim() !== "" && Number(skipMessagedHours) > 0 && `skip messaged in ${skipMessagedHours} h`,
  ].filter(Boolean).join(" · ");
  const ROW = "grid gap-1.5 sm:grid-cols-[96px_1fr] sm:gap-4";
  const LBL = "pt-1 text-[14px] text-fg-dim";

  return (
    <div className="space-y-4 rounded-lg border border-border bg-panel p-4 max-sm:rounded-none max-sm:border-x-0">
      <header className="flex items-center justify-between gap-2">
        <h3 className="min-w-0 truncate text-[14px] font-medium text-fg">Start funnel · {funnel.name}</h3>
        <IfButton variant="link" icon={X} aria-label="Close" onClick={onClose} className="w-8 text-muted hover:text-fg" />
      </header>

      <div className={ROW}>
        <span className={LBL}>Opener</span>
        <div>
          <div className="max-w-[520px] whitespace-pre-wrap rounded-lg rounded-tl-sm bg-bg-elev-2 px-3 py-2 text-[14px] text-fg">
            {funnel.opening_message}
          </div>
          <IfHelp>Sent now, free. {funnel.step_count > 0
            ? `${funnel.step_count} follow-up step${funnel.step_count === 1 ? "" : "s"} go out as fans reply.`
            : "No follow-up steps."}</IfHelp>
        </div>
      </div>

      {!accountId && (
        <div className="text-[12px] text-warn">Pick a model (account) in the chips above first.</div>
      )}

      <div className={ROW}>
        <span className={LBL}>Send to</span>
        <div className="space-y-1.5">
          <ChipRow items={SYSTEM_AUDIENCES} side="in" />
          {listItems.length > 0 && <ChipRow items={listItems} side="in" />}
        </div>
      </div>

      {/* Exclude: custom lists only; OF silently drops built-in names in excludedLists, so "All fans" would over-send. */}
      {listItems.length > 0 && (
        <div className={ROW}>
          <span className={LBL}>Exclude</span>
          <div>
            <ChipRow items={listItems} side="out" />
            <IfHelp>{MASS_EXCLUDE_LIST_NAME} is excluded by default; fans who already answered are skipped.</IfHelp>
          </div>
        </div>
      )}

      <div className={ROW}>
        <span className="max-sm:hidden" />
        <div>
          <button type="button" aria-expanded={more} onClick={() => setMore(!more)}
            className="inline-flex items-center gap-1 text-[13px] text-accent hover:text-accent-hover">
            <ChevronRight aria-hidden className={cn("h-3.5 w-3.5 transition-transform", more && "rotate-90")} />
            More options
            <span className="text-muted">· {moreSummary}</span>
          </button>
          {more && (
            <div className="mt-3 space-y-4">
              <IfSwitch label="Online only" checked={onlineOnly} onChange={(on) => { setDone(null); setOnlineOnly(on); }}
                className="flex" />
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <IfLabel htmlFor={`funnel-${funnel.id}-skip`}>Skip fans I messaged in the last … hours</IfLabel>
                  <IfInput id={`funnel-${funnel.id}-skip`} type="number" min={0} className="w-28" placeholder="e.g. 2"
                    value={skipMessagedHours} onChange={(e) => { setDone(null); setSkipMessagedHours(e.target.value); }} />
                  <IfHelp>blank = skip no one</IfHelp>
                </div>
                <div>
                  <IfLabel htmlFor={`funnel-${funnel.id}-unsend`}>Auto-unsend opener after … hours</IfLabel>
                  <IfInput id={`funnel-${funnel.id}-unsend`} type="number" min={0} className="w-28" placeholder="e.g. 4"
                    value={unsendHours} onChange={(e) => { setDone(null); setUnsendHours(e.target.value); }} />
                  <IfHelp>Unsent: new repliers stop enrolling; open chats keep going.</IfHelp>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className={ROW}>
        <span className="max-sm:hidden" />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <IfButton variant="primary" icon={send.isPending ? undefined : Play} onClick={confirmAndSend}
            disabled={send.isPending || !accountId || !seeded}>
            {send.isPending ? "Sending…" : "Start funnel"}
          </IfButton>
          {!done && !send.isError && (
            <span className="text-[12px] text-muted">
              {followUpsOn
                ? "Follow-ups are on for this creator."
                : `Also turns on Follow up on replies for ${accountName || "this creator"} (checks every 2 min).`}
            </span>
          )}
          {done && <span className="text-[12px] text-ok">{done}</span>}
          {send.isError && (
            <span className="text-[12px] text-err">{(send.error as Error)?.message || "Send failed"}</span>
          )}
        </div>
      </div>
    </div>
  );
}
