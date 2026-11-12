/**
 * Auto Funnel's list pure bits (FunnelEditor's table):
 *  - `funnelStatus`: one model's funnel stats (GET /admin/funnels?account_id=) + the follow-up switch → the
 *    Status pill (Smart Messages' pills: Scheduled grey, Active blue, Completed green, Canceled orange).
 *  - `startedAgo`: "40 min ago" for the Last started column.
 */

import type { PillStatus } from "@/components/automations/StatusPill";
import type { FunnelStats } from "@/hooks/useFunnels";

export type FunnelStatus = PillStatus & { hint: string };

/** Running: fans being walked, or a run still taking new repliers, with follow-ups on. Paused: the same with them
 *  off (nothing moves). Completed: started before, nobody left to walk. Not started: never sent on this model. */
export function funnelStatus(stats: FunnelStats | undefined, followUpsOn: boolean): FunnelStatus | null {
  if (!stats) return null;
  if (!stats.last_started_at) return { label: "Not started", tone: "idle", hint: "Never started on this creator." };
  const live = stats.active_fans > 0 || stats.listening;
  if (live && !followUpsOn) {
    return { label: "Paused", tone: "warn", hint: "Follow up on replies is off: no step is sent until it is on." };
  }
  if (live) {
    return { label: "Running", tone: "active", hint: stats.active_fans > 0
      ? "Fans who replied are being walked through the steps."
      : "Waiting for fans to reply to the opener." };
  }
  return { label: "Completed", tone: "ok", hint: "Every fan who replied has been through the steps." };
}

/** "just now" / "12 min ago" / "3 h ago" / "4 d ago"; null for never. */
export function startedAgo(iso: string | null | undefined, now: number = Date.now()): string | null {
  if (!iso) return null;
  // The relay writes naive UTC.
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (!Number.isFinite(t)) return null;
  const mins = Math.floor((now - t) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return `${Math.floor(hrs / 24)} d ago`;
}
