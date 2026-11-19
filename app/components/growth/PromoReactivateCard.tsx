"use client";

/**
 * PromoReactivateCard — Infloww's "Auto-activate campaign" row (bundle: ProfilePromotionCampaign), read-only: the
 * per-campaign "Keep running" tick in Campaign insights (or in Create promotion, on by default) is the one switch,
 * and the relay turns the promo_reactivate rule on/off with it. This row says which campaign keeps running and the
 * last check (the rule's last run); a warning when a campaign is ticked but its rule is missing, off or a dry run (an
 * old setup: untick and tick again). Infloww's switch and "Offer expiration" select are not built: the re-arm keeps
 * each campaign's own.
 */

import { IfHelp } from "@/components/ui/infloww";
import { RunStats, isDryRun } from "@/lib/runStats";
import { usePromotions } from "@/hooks/useGrowth";
import { useAutomationRules } from "@/hooks/useAutomations";

export default function PromoReactivateCard({ accountId }: { accountId: string | null }) {
  const promosQ = usePromotions(accountId);
  const armed = (promosQ.data?.campaigns ?? []).filter((c) => c.auto_reactivate);

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
          ? <span className="text-fg">{`Keeping “${armed.map((c) => c.name).join("”, “")}” running`}</span>
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
      {stale && (
        <div role="alert" className="text-[14px] text-warn">
          Keep running is ticked but its automation is {!rule ? "missing" : !rule.is_enabled ? "off" : "in dry run"} —
          untick and tick it again to fix.
        </div>
      )}
    </section>
  );
}
