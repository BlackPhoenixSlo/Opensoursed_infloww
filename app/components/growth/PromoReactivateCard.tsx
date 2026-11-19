"use client";

/**
 * PromoReactivateCard — Infloww's "Auto-activate campaign" row (bundle: ProfilePromotionCampaign), read-only: the
 * per-campaign "Keep running" tick in Campaign insights (or in Create promotion, on by default) is the one switch,
 * and the relay turns the promo_reactivate rule on/off with it. This row says which campaign keeps running and the
 * last check (the rule's last run); a warning when a campaign is ticked but its rule is missing, off or a dry run (an
 * old setup: untick and tick again). Infloww's switch and "Offer expiration" select are not built: the re-arm keeps
 * each campaign's own. A campaign Inflowwww turned off stays listed with its reason (`keep_warning`, until a re-tick),
 * and one held now says why (`keep_blocked`); each line names who fixes it. A Free trial kept running says how many
 * re-creates its Re-create limit has left. With Re-create at 90% filled it re-creates early, unless the server switch is
 * off (`keep_blocked` switch) or the last run waited (`keep_wait`, the line says why).
 */

import { IfHelp } from "@/components/ui/infloww";
import { preemptUsable } from "@/components/growth/createPromotionForm";
import { parseUtc } from "@/lib/format";
import { RunStats, isDryRun } from "@/lib/runStats";
import { usePromotions, type PromoCampaign } from "@/hooks/useGrowth";
import { useAutomationRules } from "@/hooks/useAutomations";

/** Why Inflowwww turned Keep running off (service/promo_create_guard.OFF_TEXT). */
const OFF_REASON: Record<string, string> = {
  create_unknown: "a promo create got no clear answer from OnlyFans and never showed up — check the promos on " +
    "OnlyFans, then tick Keep running again",
  breaker: "3 promos in a row got no new claims or never went live — check the offer, then tick Keep running again",
  price_free: "OnlyFans refused the promo because the page is free — set a subscription price on OnlyFans, then " +
    "tick Keep running again",
  captcha: "OnlyFans asked for a captcha — open the account on OnlyFans, then tick Keep running again",
  deactivated: "this Creator is deactivated — activate it, then tick Keep running again",
  rate_limited: "OnlyFans refused two promo creates in a row (rate limit or block) — wait a while, then tick Keep " +
    "running again",
  create_refused: "OnlyFans refused the promo create — check the offer, then tick Keep running again",
  limit_reached: "the free trial used up its Re-create limit — tick Keep running again to set a new one",
  limit_needed: "this free trial was ticked before free trials needed an Offer limit and a Re-create limit — tick " +
    "Keep running again to set them",
  kept_duplicate: "another campaign of this Creator was also set to keep running, and only one can be — tick Keep " +
    "running again on the one you want",
};
/** What stops a ticked campaign until someone acts (service/promo_create_guard.FENCE_TEXT / RETICK_TEXT). */
const ACT: Record<string, string> = {
  fence: "This server is not set to create promos — ask the owner to set it up",
  retick: "Tick Keep running again",
};
/** What holds a ticked campaign now. */
const HELD: Record<string, string> = {
  unknown: "waiting for OnlyFans to show the last re-create — Inflowwww checks on its next look, nothing to do",
  backoff: "the last re-create failed, so Inflowwww waits before trying again — nothing to do",
  budget: "3 re-creates this hour (or 8 today) is the most Inflowwww makes — nothing to do",
};

/** Why a live Kept promo was not re-created early (service/promo_keep_decide wait_reason). */
const WAIT: Record<string, string> = {
  count_untrusted: "the claim count isn't reliable yet",
  end_unconfirmed: "OnlyFans' end time isn't confirmed yet",
  clock: "OnlyFans' clock doesn't match ours",
  second_live: "another promo is live too",
  breaker_hold: "the last re-create hasn't shown up on OnlyFans yet",
  backoff: "the last re-create failed",
  budget: "3 re-creates this hour (or 8 today) reached",
  no_recovery_slot: "keeping a re-create spare in case one fails",
  cooldown: "the last re-create was moments ago",
};
const SWITCH_OFF = "Re-create at 90% filled is off on this server — ask the owner";

/** Re-create at 90% filled can act now: ticked, a cap of 10 or more, the server switch on, not waiting. */
export function preemptActs(c: PromoCampaign): boolean {
  return c.auto_reactivate && !!c.preempt && preemptUsable(c.subscribe_counts) && c.keep_blocked !== "switch" && !c.keep_wait;
}

/** " until 14:05" (today) or " until Nov 20, 14:05": when a back-off or the Create budget lets the next re-create. */
function until(iso: string | null | undefined): string {
  const d = parseUtc(iso);
  if (!d) return "";
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString()
    ? ` until ${time}` : ` until ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${time}`;
}

/** The campaign's lines, each naming who fixes it; `off`: someone must act (a stop, the fence, a re-tick), else a
 *  hold that clears itself or the Re-create limit left. */
export function keepLines(c: PromoCampaign): { text: string; off: boolean }[] {
  const lines: { text: string; off: boolean }[] = [];
  if (c.keep_warning) {
    lines.push({ text: `Keep running is off: ${OFF_REASON[c.keep_warning] ?? "tick Keep running again"}`, off: true });
  }
  if (c.keep_blocked && ACT[c.keep_blocked]) {
    lines.push({ text: `Not re-creating: ${ACT[c.keep_blocked]}`, off: true });
  } else if (c.keep_blocked === "switch") {
    // The owner's kill switch: After-end re-create still runs, so a status, not a warning. A cap under 10 never
    // pre-empts, so the switch says nothing about it (the relay's row may still hold the default tick).
    if (preemptUsable(c.subscribe_counts)) lines.push({ text: SWITCH_OFF, off: false });
  } else if (c.keep_blocked && c.keep_blocked !== "clock") {   // clock: the waiting line below says it
    const why = HELD[c.keep_blocked] ?? c.keep_blocked;
    lines.push({ text: `Paused${until(c.keep_blocked_until)}: ${why}`, off: false });
  }
  if (c.keep_wait) {
    const why = WAIT[c.keep_wait];
    lines.push({ text: `Waiting: will re-create after it ends${why ? ` (${why})` : ""}`, off: false });
  }
  if (c.auto_reactivate && c.recreates_left != null) {
    const n = c.recreates_left;
    lines.push({ text: `${n} re-create${n === 1 ? "" : "s"} left, then Keep running turns off`, off: false });
  }
  return lines;
}

export default function PromoReactivateCard({ accountId }: { accountId: string | null }) {
  const promosQ = usePromotions(accountId);
  const campaigns = promosQ.data?.campaigns ?? [];
  const armed = campaigns.filter((c) => c.auto_reactivate);
  const flagged = campaigns.filter((c) => c.id != null && keepLines(c).length > 0);

  const rulesQ = useAutomationRules(accountId);
  const rule = (rulesQ.data ?? []).find((r) => r.kind === "promo_reactivate") ?? null;
  const stale = armed.length > 0 && rulesQ.isSuccess && (!rule || !rule.is_enabled || isDryRun(rule));

  const last = rule?.last_run;
  return (
    <section aria-label="Auto-activate campaign" className="space-y-1">
      <div className="text-[16px] font-medium text-fg">Auto-activate campaign</div>
      <p className="mt-1 text-[14px] text-fg-dim">
        Tick <b>Keep running</b> on a campaign to re-create it within about 2 minutes of ending
      </p>
      <IfHelp data-promo-reactivate-status>
        {armed.length > 0
          ? <><span className="text-fg">{`Keeping “${armed.map((c) => c.name).join("”, “")}” running`}</span>
            <span>{" · "}{armed.every(preemptActs) ? "Re-creates at 90% filled or shortly before it ends"
              : "Re-creates after it ends"}</span></>
          : <span>No campaign is set to keep running</span>}
        {armed.length > 0 && last && (
          <span>
            {" · "}Last check: <span className="text-fg">{last.status}</span>
            <RunStats stats={last.stats} />
            {last.started_at && ` · ${new Date(last.started_at).toLocaleString()}`}
            {last.error_text && <span className="text-err"> · {last.error_text}</span>}
          </span>
        )}
      </IfHelp>
      {flagged.map((c) => keepLines(c).map((line) => (
        <div key={`${c.id}:${line.text}`} role={line.off ? "alert" : "status"}
          className={`break-words text-[14px] ${line.off ? "text-warn" : "text-fg-dim"}`}>
          <span className="text-fg">{`“${c.name}”`}</span>: {line.text}
        </div>
      )))}
      {stale && (
        <div role="alert" className="text-[14px] text-warn">
          Keep running is ticked but its automation is {!rule ? "missing" : !rule.is_enabled ? "off" : "in dry run"} —
          untick and tick it again to fix.
        </div>
      )}
    </section>
  );
}
