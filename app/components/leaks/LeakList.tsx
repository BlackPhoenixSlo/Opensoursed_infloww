"use client";

import { FileText, Folder, HardDrive, Image as ImageIcon, Link as LinkIcon, Send, type LucideIcon } from "lucide-react";
import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";

import { TableSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, IfButton } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

import { useLeakPages } from "./leakRead";
import { KIND_LABEL, LEGEND, PILL_LABEL, seenNote, timeline, viewerZone, type Leak, type LeakPage, type LeakPill } from "./leakView";

const KIND_ICON: Record<string, LucideIcon> = { page: FileText, mega: Folder, telegram: Send, file_host: HardDrive, media: ImageIcon };

const PILL_CLASS: Record<LeakPill, string> = {
  live: "bg-err/10 text-err",
  cached: "bg-warn/10 text-warn",
  gone: "bg-ok/10 text-ok",
  listed: "bg-accent/10 text-accent",
  not_checked: "border border-border text-muted",
};

const NOT_REACHABLE_LEAKS = "The removal service is not reachable. Leaks show again once it answers.";

function Pill({ pill }: { pill: LeakPill }) {
  return (
    <span data-pill={pill} className={cn("rounded-full px-2 py-0.5 text-[12px] font-medium", PILL_CLASS[pill])}>
      {PILL_LABEL[pill]}
    </span>
  );
}

function LeakLegend() {
  return (
    <ul aria-label="Pills legend" className="mt-4 flex flex-col gap-1.5 text-[13px] text-muted">
      {LEGEND.map(([pill, text]) => (
        <li key={pill} className="flex flex-wrap items-center gap-2"><Pill pill={pill} />{text}</li>
      ))}
    </ul>
  );
}

type CreatorLink = { names: Record<string, string>; pick: (accountId: string) => void };

function LeakRows({ label, leaks, creator }: { label: string; leaks: Leak[]; creator?: CreatorLink }) {
  const now = new Date();
  const tz = viewerZone();
  return (
    <ul aria-label={label} className="divide-y divide-border">
      {leaks.map((l) => {
        const Icon = KIND_ICON[l.kind] ?? LinkIcon;
        const events = l.events && timeline(l.events, now, tz);
        const aid = l.account_id;
        return (
          <li key={`${aid ?? ""}:${l.leak_id}`} data-leak={l.leak_id} className="flex min-w-0 flex-col gap-1 py-3 text-[14px]">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              {creator && aid && (
                <IfButton variant="link" className="h-auto" onClick={() => creator.pick(aid)}>{creator.names[aid] ?? aid}</IfButton>
              )}
              <Pill pill={l.pill} />
              {l.came_back && <span className="rounded-full bg-err/10 px-2 py-0.5 text-[12px] text-err">Came back</span>}
              <span data-leak-kind={l.kind} className="inline-flex items-center gap-1 text-muted">
                <Icon aria-hidden="true" className="h-4 w-4" />{KIND_LABEL[l.kind] ?? l.kind}
              </span>
              <span className="text-muted">{l.leak_site}</span>
            </div>
            <a href={l.url} target="_blank" rel="noreferrer noopener" className="min-w-0 break-all text-accent hover:text-accent-hover">
              {l.title || l.url}
            </a>
            <span className="text-[13px] text-muted">{seenNote(l, now, tz)}</span>
            {events && events.length > 0 && (
              <ol aria-label="Timeline" className="flex flex-wrap gap-x-3 text-[13px] text-muted">
                {events.map((e, i) => <li key={i}>{e}</li>)}
              </ol>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function LeakPages({ label, query, creator }: {
  label: string;
  query: UseInfiniteQueryResult<InfiniteData<LeakPage>>;
  creator?: CreatorLink;
}) {
  const pages = query.data?.pages ?? [];
  let body;
  if (pages[0]?.leaks === null) body = <p className="text-[14px] text-muted">{NOT_REACHABLE_LEAKS}</p>;
  else {
    const leaks = pages.flatMap((p) => p.leaks ?? []);
    body = (
      <>
        {pages.some((p) => p.stale) && <p className="mb-2 text-[13px] text-muted">Showing the last good copy.</p>}
        {leaks.length ? <LeakRows label={label} leaks={leaks} creator={creator} />
          : <p className="text-[14px] text-muted">No Leaks found yet.</p>}
        {query.isFetchNextPageError && <p role="alert" className="mt-3 text-[14px] text-err">Couldn&apos;t load more Leaks.</p>}
        {query.hasNextPage && (
          <IfButton className="mt-3" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>Load more</IfButton>
        )}
      </>
    );
  }
  return (
    <>
      {body}
      <LeakLegend />
    </>
  );
}

export function AllLeaks({ accountId, names, onPick }: {
  accountId: string | null;
  names: Record<string, string>;
  onPick: (accountId: string) => void;
}) {
  const all = useLeakPages<LeakPage>(["leak-tracker", "all", accountId], "/admin/leaks/all", accountId);
  return (
    <section aria-label="All Models">
      <h2 className="mb-2 text-[16px] font-medium text-fg">All Leaks</h2>
      {all.isPending ? <TableSkeleton rows={4} />
        : all.data ? <LeakPages label="All Leaks" query={all} creator={{ names, pick: onPick }} />
        : <EmptyState kind="error" className="mt-12" text="Couldn't load the Leaks." onRetry={() => void all.refetch()} />}
    </section>
  );
}
