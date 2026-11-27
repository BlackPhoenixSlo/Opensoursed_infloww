"use client";

import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { NotAvailable } from "@/components/shell/NotAvailable";
import { NoCreators } from "@/components/shell/NoCreators";
import { useFlags } from "@/components/shell/useFlags";
import { IfCreatorSelect, useSetCreatorParam } from "@/components/ui/infloww";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { useAccountLabel } from "@/hooks/useAccounts";
import { fanslyRouteOf } from "@/lib/fansly-mirror-route";
import { useFanslyPick } from "@/lib/fanslyMirrorPick";
import { ofMeQuery } from "@/lib/ofMe";

export function FanslyMirrorChrome({ children }: { children: React.ReactNode }) {
  const [section = "", ...path] = (usePathname() ?? "").split("/").filter(Boolean).slice(1);
  const flags = useFlags();
  const route = fanslyRouteOf(section, path, null);
  if (route?.kind !== "mirror") return <>{children}</>;

  if (!flags) return <div className="p-4"><TableSkeleton rows={6} /></div>;
  if (!flags.fansly_manager) return <NotAvailable label={route.label} />;
  return <Chrome label={route.label}>{children}</Chrome>;
}

function Chrome({ label, children }: { label: string; children: React.ReactNode }) {
  const { failed, live, pick, shown } = useFanslyPick();
  const pickCreator = useSetCreatorParam();

  return (
    <div className="flex flex-col" data-testid="fansly-mirror-chrome">
      <div className="h-12 shrink-0 flex items-center gap-4 px-6 border-b border-border box-border">
        <h1 className="text-base font-medium text-fg truncate">{label}</h1>
        {live.length > 0 && <IfCreatorSelect accounts={live} value={shown} onChange={pickCreator} searchable />}
      </div>
      {pick.kind === "standIn" && <StandInHint accountId={pick.accountId} />}
      <div style={{ ["--shell-top" as string]: "calc(var(--chrome-top) + 48px)" }}>
        {pick.kind === "loading" ? <div className="p-4"><TableSkeleton rows={6} /></div> : pick.kind === "none" && !failed ? <NoCreators className="h-chat" /> : children}
      </div>
    </div>
  );
}

function StandInHint({ accountId }: { accountId: string }) {
  const nickname = useAccountLabel(accountId);
  const name = useQuery(ofMeQuery(accountId)).data?.name || nickname;
  return (
    <div className="shrink-0 px-6 py-1.5 text-xs text-fg-dim border-b border-border" data-testid="fansly-standin-hint">
      Showing {name}, pick a model to switch
    </div>
  );
}
