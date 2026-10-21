"use client";

/**
 * useAccessChangeNotices — a chatter's toast when the Agency changes what it
 * may do: "Your permissions were updated." and "You've been unassigned from
 * <Creator>." (Infloww's live revoke, 04 M20).
 *
 * `permissions_changed` and `assignment_changed` are Agency-wide and empty:
 * every session of the Agency gets them whoever's grants moved. So each one
 * snapshots what it covers, and the refetch it triggers
 * (useAccountStateEvents) is compared with that: only the session whose own
 * applied permissions or Creator list changed is told. An owner session
 * makes these changes and is never told.
 */

import { useEffect } from "react";
import { useQueryClient, type Query, type QueryClient } from "@tanstack/react-query";

import { useOptionalChatter, type ChatterFlatAccountDTO } from "@/contexts/ChatterContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { APPLIED_SETTINGS_KEY, type AppliedSettings } from "@/lib/appliedSettings";
import { chatterAccountsQuery } from "@/lib/chatterAccounts";
import { eventBus } from "@/lib/events";
import { pushNotice } from "@/lib/notices";
import { isChatterOnly } from "@/lib/session";

/** A refetch that has not landed by then is not this event's. */
export const SETTLE_MS = 30_000;
const LABEL = "Access";

/** Call `fn` with each query matching `prefix` whose data a fetch replaces,
 *  until it returns true or SETTLE_MS passes. A `setQueryData` (logout's
 *  `[]`) is no fetch, and a failed fetch replaces nothing. */
function onRefetched(qc: QueryClient, prefix: readonly unknown[], fn: (q: Query) => boolean): void {
  const stop = () => { clearTimeout(timer); unsubscribe(); };
  const timer = setTimeout(stop, SETTLE_MS);
  const unsubscribe = qc.getQueryCache().subscribe((ev) => {
    if (ev.type !== "updated" || ev.action.type !== "success" || ev.action.manual) return;
    if (!prefix.every((k, i) => ev.query.queryKey[i] === k)) return;
    if (fn(ev.query)) stop();
  });
}

const grants = (d: AppliedSettings | undefined) =>
  d && JSON.stringify([d.permissions, d.messaging]);

export function useAccessChangeNotices(): void {
  const qc = useQueryClient();
  const chatterOnly = isChatterOnly(useOptionalUser()?.user, useOptionalChatter()?.chatter);

  useEffect(() => {
    if (!chatterOnly) return;
    const offs = [
      eventBus.on("assignment_changed", () => {
        const before = qc.getQueryData<ChatterFlatAccountDTO[]>(chatterAccountsQuery.queryKey);
        if (!before?.length) return;
        onRefetched(qc, chatterAccountsQuery.queryKey, (q) => {
          const kept = new Set((q.state.data as ChatterFlatAccountDTO[]).map((a) => a.account_id));
          for (const a of before) {
            if (kept.has(a.account_id)) continue;
            pushNotice({
              id: `unassigned:${a.account_id}`,
              text: `You've been unassigned from ${a.nickname || a.account_id}.`,
              label: LABEL,
            });
          }
          return true;
        });
      }),
      eventBus.on("permissions_changed", () => {
        const before = new Map(
          qc.getQueriesData<AppliedSettings>({ queryKey: APPLIED_SETTINGS_KEY })
            .map(([key, data]) => [JSON.stringify(key), grants(data)]),
        );
        onRefetched(qc, APPLIED_SETTINGS_KEY, (q) => {
          const was = before.get(JSON.stringify(q.queryKey));
          if (was === undefined) return false;
          if (was !== grants(q.state.data as AppliedSettings)) {
            pushNotice({ id: "permissions-changed", text: "Your permissions were updated.", label: LABEL });
          }
          return true;
        });
      }),
    ];
    return () => offs.forEach((off) => off());
  }, [qc, chatterOnly]);
}
