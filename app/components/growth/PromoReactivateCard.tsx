"use client";

/**
 * PromoReactivateCard — Infloww's "Auto-activate campaign" row (bundle: ProfilePromotionCampaign), read-only: the
 * per-campaign "Keep running" tick in Campaign insights (or in Create promotion, on by default) is the one switch,
 * and the relay turns the promo_reactivate rule on/off with it. This row says which campaign keeps running and the
 * last check (the rule's last run); a warning when a campaign is ticked but its rule is missing, off or a dry run (an
 * old setup: untick and tick again). Infloww's switch and "Offer expiration" select are not built: the re-arm keeps
 * each campaign's own. What Inflowwww says about a campaign (turned off and why, held now, waiting, re-creates left) is
 * `keep_lines`, the relay's finished text; each line names who fixes it. With Re-create at 90% filled the row re-creates
 * early, unless the server switch is off (`keep_blocked` "switch") or the last run waited (`keep_wait`).
 */

import { IfHelp } from "@/components/ui/infloww";
import { preemptUsable } from "@/components/growth/createPromotionForm";
import { parseUtc } from "@/lib/format";
import { RunStats, isDryRun } from "@/lib/runStats";
import { usePromotions, type PromoCampaign } from "@/hooks/useGrowth";
import { useAutomationRules } from "@/hooks/useAutomations";

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

/** The campaign's lines as the relay wrote them (service/promotions_api.keep_lines), each naming who fixes it;
 *  `off`: someone must act (a stop, the fence, a re-tick), else a hold that clears itself or the Re-create limit left. */
export function keepLines(c: PromoCampaign): { text: string; off: boolean }[] {
  return c.keep_lines.map((l) => ({ text: l.lead ? `${l.lead}${until(l.until)}: ${l.text}` : l.text, off: l.off }));
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
        Tick <b>Keep running</b> on a campaign to re-create it once it ends — usually within minutes, checked at least hourly
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
