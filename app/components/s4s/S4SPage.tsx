"use client";

/**
 * One Share for Share page (Inventory §3.6; docs/spec/phase-03-share-for-share.md, UI), on Infloww's frame (`Index$7`,
 * page-parity 15): the 48px legacy header (with "Date/Time shown in UTC time zone" on Requests and S4S schedule),
 * then the 300px creator rail (`pageScene:"s4s"`: the S4S tag on opted-in creators, the count of new requests) beside
 * the section. The picked creator lives in `?creator=` (default the first) and every section shows that creator
 * only: each S4S record already names its creator's profile, so the rail is a client-side filter. Below md the rail
 * gives way to the creator select. Owner-only: a chatter reaching the route by URL gets a sentence and the page calls
 * no S4S route (the Relay 403s `/admin/s4s` anyway).
 */

import { useMemo } from "react";

import { CreatorColumn, type S4SMark } from "@/components/of-manager/CreatorColumn";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import DiscoverCreators from "@/components/s4s/DiscoverCreators";
import S4SRequests from "@/components/s4s/S4SRequests";
import S4SSchedule from "@/components/s4s/S4SSchedule";
import S4SSettingPanel from "@/components/s4s/S4SSettingPanel";
import { UTC_NOTE } from "@/components/s4s/s4sBits";
import { EmptyState, IfCreatorSelect, InflowwPageHeader, useCreatorParam } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useS4SProfiles, useS4SRequests } from "@/lib/s4s";

export type S4SSection = "discover-creators" | "requests" | "schedule" | "settings";

export default function S4SPage({ title, section }: { title: string; section: S4SSection }) {
  const chatterOnly = useIsChatterOnly();
  const utc = section === "requests" || section === "schedule";
  return (
    <div className="flex min-h-full flex-col">
      <InflowwPageHeader title={title} extra={utc && !chatterOnly ? <span className="text-[14px] text-[#999]">{UTC_NOTE}</span> : undefined} />
      {chatterOnly
        ? <p className="px-6 py-4 text-sm text-fg-dim">Only the agency owner manages Share for Share.</p>
        : <OwnerBody section={section} />}
    </div>
  );
}

function OwnerBody({ section }: { section: S4SSection }) {
  const accounts = useActiveAccounts();
  const [accountId, setAccountId] = useCreatorParam(accounts);
  const profilesQ = useS4SProfiles();
  const receivedQ = useS4SRequests("received");
  const profiles = profilesQ.data?.profiles;
  const profile = profiles?.find((p) => p.account_id === accountId) ?? null;

  // The rail's marks: opted in, and the pending requests sent to each creator's profile.
  const marks = useMemo(() => {
    const out: Record<string, S4SMark> = {};
    for (const p of profiles ?? []) {
      const pending = (receivedQ.data ?? []).filter((r) => r.status === "pending" && p.profile_id != null && r.to.profile_id === p.profile_id).length;
      out[p.account_id] = { optedIn: p.opted_in, pending };
    }
    return out;
  }, [profiles, receivedQ.data]);

  let body;
  if (!accountId) body = <EmptyState kind="creator" text="No creator connected yet" className="py-24" />;
  else if (section === "discover-creators") body = <DiscoverCreators from={profile} />;
  else if (section === "requests") body = <S4SRequests profile={profile} accountId={accountId} />;
  else if (section === "schedule") body = <S4SSchedule profile={profile} livePosting={profilesQ.data?.live_posting} />;
  else body = <S4SSettingPanel key={accountId} query={profilesQ} profile={profile} />;

  return (
    // `.h-chat` on the rail subtracts the 48px header too.
    <div className="flex flex-1" style={{ ["--shell-top" as string]: "calc(var(--chrome-top) + 48px)" }}>
      <CreatorColumn
        variant="s4s"
        accounts={accounts}
        value={accountId}
        onChange={setAccountId}
        marks={marks}
        className="md:flex border-r border-border"
      />
      <div className="min-w-0 flex-1 bg-bg">
        {accounts.length > 0 && (
          <div className="px-4 pt-4 md:hidden">
            <IfCreatorSelect accounts={accounts} value={accountId} onChange={setAccountId} />
          </div>
        )}
        {body}
      </div>
    </div>
  );
}
