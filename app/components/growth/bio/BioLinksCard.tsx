"use client";

/** The bio editor's Links card: the page's links in their public order, each with ↑ / ↓ (a reorder write), Edit (the
 *  link dialog) and Delete; "Add link" opens the dialog on a new one. */
import { ArrowDown, ArrowUp, Link2, Lock, Plus } from "lucide-react";

import { IfButton, IfCard } from "@/components/ui/infloww";
import { ConfirmDeleteButton } from "@/components/growth/_bits";
import {
  isBioMode, bioFailure, useDeleteBioLink, useReorderBioLinks, type BioLink, type BioPage,
} from "@/hooks/useBioPages";
import { moveLink } from "@/components/growth/bio/bioLinksOrder";
import { MODE_NAMES } from "@/components/growth/bio/bioBits";

const modeLabel = (m: string) => isBioMode(m) ? MODE_NAMES[m] : "Profile default";

export function BioLinksCard({ page, onAdd, onEdit }: {
  page: BioPage;
  onAdd: () => void;
  onEdit: (link: BioLink) => void;
}) {
  const pid = page.profile.id;
  const reorder = useReorderBioLinks(pid);
  const remove = useDeleteBioLink(pid);
  const links = page.links;
  const ids = links.map((l) => l.id);
  const pending = reorder.isPending || remove.isPending;
  const error = reorder.error ?? remove.error;

  const move = (id: string, dir: -1 | 1) => {
    const next = moveLink(ids, id, dir);
    if (next !== ids) reorder.mutate([...next]);
  };

  return (
    <IfCard title={`Links${links.length ? ` · ${links.length}` : ""}`}
      extra={<IfButton variant="primary" icon={Plus} onClick={onAdd}>Add link</IfButton>}>
      {links.length === 0 ? (
        <p className="mt-4 text-sm text-fg-dim">No links yet. Add the first one: it shows as a card on the page.</p>
      ) : (
        <ul aria-label="Links" className="mt-3 divide-y divide-border">
          {links.map((l, i) => (
            <li key={l.id} data-bio-link={l.title} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
              <Thumb link={l} />
              <div className="min-w-0 flex-1 basis-40">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-sm font-medium text-fg">{l.title}</span>
                  {l.is_adult && <Lock aria-label="18+" className="h-3.5 w-3.5 shrink-0 text-fg-dim" />}
                  <span className="shrink-0 rounded bg-bg-elev-2 px-1.5 text-[11px] text-fg-dim">{modeLabel(l.mode)}</span>
                </div>
                <div className="truncate text-[12px] text-fg-dim" title={l.destination}>{l.destination}</div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <IfButton variant="link" icon={ArrowUp} aria-label={`Move ${l.title} up`}
                  disabled={pending || i === 0} onClick={() => move(l.id, -1)} className="w-8 max-md:h-10 max-md:w-10" />
                <IfButton variant="link" icon={ArrowDown} aria-label={`Move ${l.title} down`}
                  disabled={pending || i === links.length - 1} onClick={() => move(l.id, 1)} className="w-8 max-md:h-10 max-md:w-10" />
                <IfButton onClick={() => onEdit(l)} disabled={pending} aria-label={`Edit ${l.title}`}>Edit</IfButton>
                <ConfirmDeleteButton confirm={`Delete the link "${l.title}"? Its stats stay in the page's totals.`}
                  onConfirm={() => remove.mutate(l.id)} pending={pending} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {error && <p role="alert" className="mt-2 text-[12px] text-err">{bioFailure(error, "Couldn't change the links").msg}</p>}
    </IfCard>
  );
}

/** The link's background (a 2.5:1 thumb), else its icon, else a plain link glyph. */
function Thumb({ link: l }: { link: BioLink }) {
  const url = l.background_url || l.icon_url;
  if (!url) {
    return (
      <span aria-hidden className="grid h-8 w-12 shrink-0 place-items-center rounded-md bg-bg-elev-2 text-fg-dim">
        <Link2 className="h-4 w-4" />
      </span>
    );
  }
  return (
    <span aria-hidden className={`h-8 w-12 shrink-0 rounded-md bg-bg-elev-2 bg-center ${l.background_url ? "bg-cover" : "bg-contain bg-no-repeat"}`}
      style={{ backgroundImage: `url("${url}")` }} />
  );
}
