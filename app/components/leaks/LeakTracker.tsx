"use client";

import { type FormEvent } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LeakDisclaimer } from "@/components/leaks/LeakDisclaimer";
import { NotAvailable } from "@/components/shell/NotAvailable";
import { PageFrame } from "@/components/shell/PageFrame";
import { useFlags } from "@/components/shell/useFlags";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, IfButton, IfCard, IfInput, IfLabel } from "@/components/ui/infloww";
import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { relay, RelayError } from "@/lib/relay";

import { LeakCreator } from "./LeakCreator";
import { AllLeaks } from "./LeakList";
import { rosterChips, todayStrip } from "./leakCoverage";
import { leakRead } from "./leakRead";
import { LeakTodayStrip } from "./LeakTodayStrip";
import { rosterNotes, viewerZone, type LeakRoster } from "./leakView";

const TITLE = "Leak tracker";

export type LeakSetup = {
  key: "missing" | "set" | "invalid";
  masked: string | null;
  is_owner: boolean;
  can_write: boolean;
  brand: string | null;
  source: "own" | "instance" | null;
};

function KeyCard({ setup, accountId }: { setup: LeakSetup; accountId: string | null }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (key: string) => relay.put<Pick<LeakSetup, "key" | "masked" | "brand" | "source">>("/admin/leaks/key", { key }, { accountId }),
    onSuccess: (res) => {
      qc.setQueriesData<LeakSetup>({ queryKey: ["leak-tracker", "setup"] }, (prev) => (prev ? { ...prev, ...res } : prev));
    },
  });
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const key = String(new FormData(form).get("key") ?? "").trim();
    if (key) save.mutate(key, { onSuccess: () => form.reset() });
  };
  const form = (
    <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-2">
      <div className="min-w-0 flex-1">
        <IfLabel htmlFor="leak-tracker-key">Tracker key</IfLabel>
        <IfInput id="leak-tracker-key" name="key" type="password" autoComplete="off" required placeholder="ltk_…" className="w-full" />
      </div>
      <IfButton type="submit" variant="primary" disabled={save.isPending}>Save</IfButton>
    </form>
  );
  const error = save.error ? <p role="alert" className="mt-2 text-[14px] text-err">{save.error.message}</p> : null;
  if (setup.key === "set") {
    const shared = setup.source === "instance";
    return (
      <IfCard aria-label="Removal service key" className="mb-4">
        <p className="text-[14px] text-fg">
          Connected to {setup.brand ?? "the removal service"}
          {setup.masked && <> · <span className="font-mono">{setup.masked}</span></>}
        </p>
        <details className="mt-2 text-[14px]">
          <summary className="cursor-pointer text-accent">{shared ? "Use your own key" : "Change key"}</summary>
          {form}
          {!shared && (
            <IfButton variant="link" className="mt-2" disabled={save.isPending} onClick={() => save.mutate("")}>Disconnect</IfButton>
          )}
        </details>
        {error}
      </IfCard>
    );
  }
  return (
    <IfCard aria-label="Connect the removal service" title="Connect the removal service" className="max-w-[560px]">
      {setup.key === "invalid" ? (
        <p role="status" className="mt-1 text-[14px] text-err">Key no longer valid. Paste a new key from the removal service.</p>
      ) : (
        <p className="mt-1 text-[14px] text-muted">The Leak tracker needs the removal service&apos;s key for this agency.</p>
      )}
      {form}
      {error}
    </IfCard>
  );
}

export function LeakTracker() {
  const qc = useQueryClient();
  const flags = useFlags();
  const { accountId } = useScope();
  const on = flags?.leak_tracker === true;
  const setup = useQuery<LeakSetup>({
    queryKey: ["leak-tracker", "setup", accountId],
    queryFn: () => relay.get<LeakSetup>("/admin/leaks/setup", { accountId }),
    enabled: on,
  });
  const roster = useQuery<LeakRoster>({
    queryKey: ["leak-tracker", "roster", accountId],
    queryFn: () => leakRead<LeakRoster>(qc, "/admin/leaks/roster", accountId),
    enabled: on && setup.data?.key === "set",
  });
  const active = useActiveAccounts();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const open = search.get("open");
  const choose = (id: string | null) => {
    const params = new URLSearchParams(search.toString());
    if (id) params.set("open", id);
    else params.delete("open");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  if (!flags || (on && setup.isPending)) return <div className="p-4"><TableSkeleton rows={6} /></div>;
  const data = setup.data;
  if (!on || (setup.error instanceof RelayError && setup.error.status === 404)) return <NotAvailable label={TITLE} />;
  if (!data) {
    return (
      <PageFrame title={TITLE}>
        <EmptyState kind="error" className="mt-24" text={`Couldn't load the ${TITLE}.`} onRetry={() => void setup.refetch()} />
      </PageFrame>
    );
  }
  if (data.key !== "set") {
    return (
      <PageFrame title={TITLE}>
        {data.is_owner ? (
          <KeyCard setup={data} accountId={accountId} />
        ) : data.key === "invalid" ? (
          <p className="text-[14px] text-muted">Key no longer valid. Ask the agency owner to connect the removal service again.</p>
        ) : (
          <p className="text-[14px] text-muted">The agency owner has not connected the removal service yet.</p>
        )}
      </PageFrame>
    );
  }
  if (!roster.data) {
    return (
      <PageFrame title={TITLE}>
        {data.is_owner && <KeyCard setup={data} accountId={accountId} />}
        {roster.isPending ? (
          <TableSkeleton rows={6} />
        ) : (
          <EmptyState kind="error" className="mt-24" text="Couldn't load the Creators." onRetry={() => void roster.refetch()} />
        )}
      </PageFrame>
    );
  }
  const notes = rosterNotes(roster.data, new Date(), viewerZone());
  const down = roster.data.stale ? "The removal service is not reachable. Showing the last good copy."
    : roster.data.rows.some((r) => !r.reachable) ? "The removal service is not reachable." : null;
  const listed = new Set(Object.keys(notes));
  const accounts = active.filter((a) => listed.has(a.id));
  const shown = accounts.find((a) => a.id === open);
  const names = Object.fromEntries(accounts.map((a) => [a.id, a.nickname || a.id]));
  const visible = new Set(accounts.map((a) => a.id));
  const rows = roster.data.rows.filter((r) => visible.has(r.account_id));
  const strip = todayStrip(rows);
  const chips = rosterChips(rows);
  return (
    <PageFrame
      title={TITLE}
      creators={{ accounts, notes, chips, value: shown?.id ?? null, onChange: choose, all: { pick: () => choose(null), label: "All Models", row: true } }}
    >
      {strip && <LeakTodayStrip strip={strip} />}
      {data.is_owner && <KeyCard setup={data} accountId={accountId} />}
      {down && <p role="status" className="mb-4 text-[14px] text-muted">{down}</p>}
      <LeakDisclaimer brand={data.brand} />
      <div data-leak-view={shown?.id ?? "all"}>
        {shown ? (
          <LeakCreator
            key={`${accountId ?? "all"}:${shown.id}`}
            creatorId={shown.id}
            scopeAccountId={accountId}
            name={shown.nickname || shown.id}
            canWrite={data.can_write}
            brand={data.brand}
            row={roster.data.rows.find((r) => r.account_id === shown.id)}
            onDeleted={() => choose(null)}
          />
        ) : (
          <AllLeaks accountId={accountId} names={names} onPick={choose} />
        )}
      </div>
    </PageFrame>
  );
}
