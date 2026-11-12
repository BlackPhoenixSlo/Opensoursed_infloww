"use client";

/** The bio editor's Tracking URLs card, only for a page with a Creator: the page's address per OnlyFans tracking link
 *  of that Creator (`<address>/<code>`), v2 `script.js:218-250` minus its `/geo` row (no Geo Rule in the UI, 11-12). */
import { CopyButton } from "@/components/growth/_bits";
import { IfCard, IfHelp } from "@/components/ui/infloww";
import { useOfTrackingLinks } from "@/hooks/useGrowth";
import type { BioPage } from "@/hooks/useBioPages";
import { trackingRows } from "@/components/growth/bio/bioPreviewModel";

export function BioTrackingUrls({ page }: { page: BioPage }) {
  const { profile } = page;
  const q = useOfTrackingLinks(profile.account_id);
  if (!profile.account_id) return null;
  const address = profile.public_url ?? `/${profile.username}`;
  const rows = trackingRows(q.data?.links ?? [], address);

  return (
    <IfCard title="Tracking URLs">
      <IfHelp className="mt-1">Codes apply to links with OnlyFans tracking on.</IfHelp>
      {q.isLoading ? (
        <p className="mt-3 text-sm text-fg-dim">Loading the Creator&rsquo;s tracking links…</p>
      ) : rows.length === 0 ? (
        <p className="mt-3 text-sm text-fg-dim">
          {q.isError ? "Couldn't read the Creator's OnlyFans tracking links." : "The Creator has no OnlyFans tracking links yet."}
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-border">
          {rows.map((r) => (
            <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <span className="min-w-0 flex-1 basis-32 truncate text-sm text-fg">{r.name}</span>
              <span className="min-w-0 max-w-full truncate text-[13px] text-accent" title={r.url}>{r.url}</span>
              {profile.public_url && <CopyButton text={r.url} label="Copy" />}
            </li>
          ))}
        </ul>
      )}
    </IfCard>
  );
}
