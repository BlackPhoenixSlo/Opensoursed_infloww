"use client";

/**
 * ShareLinksPanel — Infloww's third tab "Share links" on Free trial links and Tracking links (bundle @14121033,
 * @14128428): a share link is a public, read-only report on some of the Creator's links for someone outside the
 * agency. Create takes a name, the links and "Include earnings"; the report can be viewed for 7 days ("Expires on"),
 * then answers that it expired. Owner-only (the tab is not drawn for a chatter; the relay refuses one too).
 *
 * The report (`/share/<id>.<secret>`, `ShareReport`) shows each link's name, date created and OnlyFans' counts, and
 * with "Include earnings" its net Earnings and Fans who spent; never a fan. Its figures are the ones this page last
 * read: the relay rebuilds them each time the links list here reads OnlyFans (Infloww: "updated at least once every
 * 4 hours"; ours has no scheduler). Delete stops the link at once.
 */

import { useState } from "react";
import { Plus, Search } from "lucide-react";

import { ExtraTag, Input } from "@/components/ui/primitives";
import { EmptyState, HbButton, HbFilterLg, HbModal } from "@/components/ui/infloww";
import { ConfirmDeleteButton, CopyButton, errMsg } from "@/components/growth/_bits";
import { FieldLabel } from "@/components/growth/LinkMetaFields";
import { CreatorFilter, LEAD, Switch, TD, TH, dateOnly, useReportTz } from "@/components/growth/LinksListFrame";
import {
  useCreateLinkShare, useLinkShares, useOfTrackingEarnings, useRevokeLinkShare, type EditableKind,
} from "@/hooks/useGrowth";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

const NOUN: Record<EditableKind, string> = { trial: "free trial links", campaign: "tracking links" };
const MAX_LINKS = 100;

/** The share's public address: same-origin, Next rewrites its data read to the relay. */
function shareUrl(path: string): string {
  return typeof window === "undefined" ? path : `${window.location.origin}${path}`;
}

export default function ShareLinksPanel({ accountId, onAccountChange, kind, links }: {
  accountId: string | null;
  onAccountChange: (id: string) => void;
  kind: EditableKind;
  /** The Creator's links that can be shared (an OnlyFans id), as the links list read them. */
  links: Array<{ ofId: number; name: string }>;
}) {
  const q = useLinkShares(accountId, kind);
  // A tracking link share is filled by the earnings read; opening the tab makes it (the free trial list is the tab's).
  useOfTrackingEarnings(kind === "campaign" ? accountId : null);
  const revoke = useRevokeLinkShare(accountId, kind);
  const { reportTz } = useReportTz();
  const [creating, setCreating] = useState(false);
  const shares = q.data?.shares ?? [];
  const live = shares.filter((s) => s.status !== "expired").length;

  return (
    <div className="px-4 pt-4 mb-4 space-y-2">
      <div className="flex flex-wrap items-center gap-x-4">
        <CreatorFilter accountId={accountId} onAccountChange={onAccountChange} />
        <div className="mb-4 ml-auto flex items-center gap-4">
          {q.data && <span className="text-sm text-fg-dim">{live} / {q.data.limit} active</span>}
          <HbButton size="lg" icon={Plus} onClick={() => setCreating(true)} disabled={!accountId || links.length === 0}>
            Create share link
          </HbButton>
        </div>
      </div>
      {q.isError && <div className="text-sm text-err">Unable to load page. Try again later</div>}
      <div className="overflow-x-auto">
        <table aria-label="Share links" className="w-full min-w-[800px] border-collapse table-fixed">
          <thead>
            <tr>
              <th className={TH} style={{ width: 220 }}>Name</th>
              <th className={TH} style={{ width: 80 }}>Links</th>
              <th className={TH} style={{ width: 140 }}>Include earnings</th>
              <th className={TH} style={{ width: 120 }}>Date created</th>
              <th className={TH} style={{ width: 120 }}>Expires on</th>
              <th className={TH} style={{ width: 240 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {q.isLoading ? (
              <tr><td colSpan={6} className={cn(TD, "text-fg-dim")}>Loading…</td></tr>
            ) : shares.length === 0 ? (
              <tr><td colSpan={6} className="h-[250px]"><EmptyState text="No data" /></td></tr>
            ) : shares.map((s) => (
              <tr key={s.id}>
                <td className={TD} title={s.name}>{s.name}</td>
                <td className={cn(TD, "tabular-nums")}>{s.of_ids.length}</td>
                <td className={TD}>{s.include_earnings ? "Yes" : "No"}</td>
                <td className={TD}>{dateOnly(s.created_at, reportTz)}</td>
                <td className={cn(TD, s.status === "expired" && "text-fg-dim")}>
                  {s.status === "expired" ? "Expired" : dateOnly(s.expires_at, reportTz)}
                  {s.status === "preparing" && <span className="ml-2 text-fg-dim">Preparing</span>}
                </td>
                <td className={cn(TD, "overflow-visible")}>
                  <span className="inline-flex items-center gap-2">
                    {s.status !== "expired" && (
                      <>
                        <CopyButton text={shareUrl(s.path)} label="Copy link" doneLabel="Link copied" holdMs={5000} />
                        <a href={s.path} target="_blank" rel="noreferrer" className="text-sm text-cta">Open</a>
                      </>
                    )}
                    <ConfirmDeleteButton
                      confirm={`Delete share link, ${s.name}? Anyone holding it can no longer open the report.`}
                      pending={revoke.isPending}
                      onConfirm={() => revoke.mutate(s.id)}
                    />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating && (
        <CreateShareModal accountId={accountId} kind={kind} links={links} onClose={() => setCreating(false)} />
      )}
    </div>
  );
}

function CreateShareModal({ accountId, kind, links, onClose }: {
  accountId: string | null;
  kind: EditableKind;
  links: Array<{ ofId: number; name: string }>;
  onClose: () => void;
}) {
  const create = useCreateLinkShare(accountId);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const [earnings, setEarnings] = useState(false);
  const [search, setSearch] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const needle = search.trim().toLowerCase();
  const shown = links.filter((l) => !needle || l.name.toLowerCase().includes(needle));
  const toggle = (id: number, on: boolean) => setPicked((p) => (on ? [...p, id] : p.filter((x) => x !== id)));

  async function save() {
    setErr(null);
    if (!name.trim()) { setErr("This is a required field"); return; }
    if (picked.length === 0) { setErr("Pick at least one link"); return; }
    try {
      await create.mutateAsync({ kind, name: name.trim(), of_ids: picked, include_earnings: earnings });
      onClose();
    } catch (e) { setErr(errMsg(e, "Unable to create share link. Try again later")); }
  }

  return (
    <HbModal
      title="Create share link"
      width={480}
      onClose={onClose}
      className="text-left whitespace-normal"
      footer={(
        <>
          <HbButton variant="secondary" onClick={onClose}>Cancel</HbButton>
          <HbButton onClick={() => void save()} disabled={create.isPending || !accountId}>Save</HbButton>
        </>
      )}
    >
      <form className="flex flex-col gap-6 text-fg" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <div className="flex flex-col gap-2">
          <FieldLabel htmlFor="share-new-name" text="Name" />
          <Input id="share-new-name" className="h-9" maxLength={100} autoFocus value={name}
            onChange={(e) => setName(e.target.value)} placeholder="e.g. For the Reddit agency" />
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="text-base mb-2">Links <span className="text-sm text-fg-dim">{picked.length} / {MAX_LINKS}</span></legend>
          <span className="relative inline-flex w-full">
            <Search size={16} aria-hidden className={LEAD} />
            <input className={cn(HbFilterLg, "w-full pl-9")} aria-label={`Search ${NOUN[kind]}`}
              placeholder={`Search ${NOUN[kind]}`} value={search} onChange={(e) => setSearch(e.target.value)} />
          </span>
          <div className="max-h-56 overflow-y-auto rounded-lg border border-border p-2 space-y-1">
            {shown.length === 0 ? <div className="text-sm text-fg-dim">No data</div> : shown.map((l) => (
              <label key={l.ofId} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={picked.includes(l.ofId)}
                  disabled={!picked.includes(l.ofId) && picked.length >= MAX_LINKS}
                  onChange={(e) => toggle(l.ofId, e.target.checked)} />
                <span className="truncate">{l.name || "(unnamed)"}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex flex-col gap-1">
          <Switch label="Include earnings" on={earnings} onChange={setEarnings} />
          <div className="-mt-3 text-xs text-fg-dim">
            Adds each link&apos;s net Earnings and Fans who spent. Fans are never shown.
          </div>
        </div>
        <div className="text-xs text-fg-dim">
          Once ready, the link can be viewed for the next 7 days. Its figures update each time this page reads the
          links from OnlyFans; while OnlyFans is not reachable they stay as last read. <span title={EXTRA_LABEL}><ExtraTag /></span>
        </div>
        {err && <div className="text-err text-xs" role="alert">{err}</div>}
      </form>
    </HbModal>
  );
}
