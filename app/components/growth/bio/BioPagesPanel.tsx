"use client";

/**
 * Tracking links' "Bio pages" tab (owner-only, an Inflowwww extra): every link-in-bio page of the owner, no Creator
 * filter (imported pages have none), with its address, Creator, link count and the last 30 days' views and clicks. A
 * row opens the page's editor; "New bio page" creates one.
 */
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";

import { EmptyState, IfButton, IfHelp } from "@/components/ui/infloww";
import { useAccounts } from "@/hooks/useAccounts";
import { bioPageHref, useBioPages, type BioListRow } from "@/hooks/useBioPages";
import { BioCreateDialog } from "@/components/growth/bio/BioCreateDialog";
import { PageAddress, PageAvatar } from "@/components/growth/bio/bioBits";
import { errMsg } from "@/components/growth/_bits";

const GRID = "md:grid md:grid-cols-[minmax(0,2fr)_minmax(0,2.4fr)_minmax(0,1.2fr)_4.5rem_5.5rem_5.5rem] md:items-center md:gap-4";
const fmt = (n: number) => n.toLocaleString("en-US");

export function BioPagesPanel() {
  const q = useBioPages();
  const [creating, setCreating] = useState(false);
  const accounts = useAccounts().data?.accounts ?? [];
  const creatorName = (id: string | null) => {
    if (!id) return "—";
    const a = accounts.find((x) => x.id === id);
    return a ? a.nickname || a.name || a.id : "Unknown Creator";
  };
  const data = q.data;
  const rows = data?.profiles ?? [];
  const notPublic = !!data && (!data.serving || !data.public_base);

  return (
    <div className="mb-4 space-y-4 px-4 pt-4">
      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Bio pages</h2>
          {rows.length > 0 && <span className="text-xs text-fg-dim">· {rows.length}</span>}
          <IfButton variant="primary" icon={Plus} className="ml-auto" onClick={() => setCreating(true)}>
            New bio page
          </IfButton>
        </div>
        <p className="text-sm text-fg-dim">
          Link-in-bio pages: a profile and its links, each link with its own OnlyFans tracking. Views and clicks are the
          last 30 days.
        </p>
        {notPublic && (
          <IfHelp role="note">
            Not public here yet: {data.public_base ? "the bio page server isn't answering" : "this server has no public bio address"},
            so visitors can&rsquo;t open these pages. You can still edit them.
          </IfHelp>
        )}
      </header>

      {q.isLoading ? (
        <p className="text-sm text-fg-dim">Loading…</p>
      ) : q.isError ? (
        <EmptyState kind="error" size="sm" text={errMsg(q.error, "Couldn't load the bio pages.")} onRetry={() => q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState size="sm" text="No bio pages yet." />
      ) : (
        <div className="rounded-[12px] bg-bg-elev-1">
          <div aria-hidden className={`hidden px-4 py-2 text-[12px] text-fg-dim ${GRID}`}>
            <span>Page</span>
            <span>Address</span>
            <span>Creator</span>
            <span className="text-right">Links</span>
            <span className="text-right">Views 30d</span>
            <span className="text-right">Clicks 30d</span>
          </div>
          <ul aria-label="Bio pages" className="divide-y divide-border">
            {rows.map((r) => <Row key={r.id} row={r} creator={creatorName(r.account_id)} />)}
          </ul>
        </div>
      )}

      {creating && <BioCreateDialog publicBase={data?.public_base ?? null} onClose={() => setCreating(false)} />}
    </div>
  );
}

/** One page: on a phone a card (name, address, then the counts in a wrapping line), from md up a table row. */
function Row({ row: r, creator }: { row: BioListRow; creator: string }) {
  const router = useRouter();
  const href = bioPageHref(r.id);
  return (
    <li data-bio-page={r.username}
      className={`cursor-pointer space-y-2 px-4 py-3 hover:bg-bg-elev-2/50 md:space-y-0 ${GRID}`}
      onClick={(e) => { if (!(e.target as HTMLElement).closest("a,button")) router.push(href); }}>
      <div className="flex min-w-0 items-center gap-3">
        <PageAvatar url={r.avatar_url} name={r.display_name} />
        <div className="min-w-0">
          <Link href={href} className="block truncate text-sm font-medium text-fg hover:text-accent">{r.display_name}</Link>
          <div className="truncate text-[12px] text-fg-dim">@{r.username}</div>
        </div>
      </div>
      <div className="min-w-0">
        <PageAddress url={r.public_url} path={`/${r.username}`} />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] md:contents">
        <span className="min-w-0 truncate text-fg-dim md:text-fg">
          <span className="md:hidden">Creator: </span>{creator}
        </span>
        <span className="tabular-nums md:text-right"><span className="text-fg-dim md:hidden">Links </span>{fmt(r.link_count)}</span>
        <span className="tabular-nums md:text-right" data-views>
          <span className="text-fg-dim md:hidden">Views </span>{fmt(r.views_30d)}
        </span>
        <span className="tabular-nums md:text-right" data-clicks>
          <span className="text-fg-dim md:hidden">Clicks </span>{fmt(r.clicks_30d)}
        </span>
      </div>
    </li>
  );
}
