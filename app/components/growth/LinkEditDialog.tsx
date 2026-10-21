"use client";

/**
 * LinkEditDialog — Infloww's Edit on a free trial link or a tracking link (its `LinkEditorFormContent`,
 * index.9f50f370.js @14007983): the link's name (read-only on edit, as Infloww's), then the shared Source, Promo
 * cost, Tag and List (`LinkMetaFields`). Source, Promo cost and Tag are kept by the relay (`PUT /admin/link-meta`) and
 * never written to OnlyFans; they feed the Profit, CPC, CPS and ROI columns and the Source and Tag filters. List is
 * OnlyFans' own add-to-list on the link's claimers, which the relay runs in the background after the save.
 *
 * `LinkBatchEditDialog` is Infloww's batch edit on the picked links (`/free-trial-link/batch/edit`,
 * `/tracking-link/batch/edit`): Source, Promo cost and Tag, each set on every link only when filled in, the rest left
 * as each link has it (`PUT /admin/link-meta/batch`). No List: that adds fans on OnlyFans, link by link.
 */

import { useState } from "react";

import { Input } from "@/components/ui/primitives";
import { HbButton, HbModal } from "@/components/ui/infloww";
import { errMsg } from "@/components/growth/_bits";
import LinkMetaFields, { FieldLabel, useLinkMetaFields, type LinkMetaValues } from "@/components/growth/LinkMetaFields";
import { useSaveLinkMeta, useSaveLinkMetaBatch, type EditableKind, type LinkMetaBatchBody } from "@/hooks/useGrowth";

const NOUN: Record<EditableKind, string> = { trial: "free trial link", campaign: "tracking link" };

export interface LinkEditTarget extends LinkMetaValues {
  kind: EditableKind;
  ofId: number;
  name: string;
}

export default function LinkEditDialog({ accountId, link, sources, tags: tagOptions, onClose }: {
  accountId: string | null;
  link: LinkEditTarget;
  /** The account's Sources and Tags in use: the inputs' suggestions. */
  sources: string[];
  tags: string[];
  onClose: () => void;
}) {
  const save = useSaveLinkMeta(accountId);
  const f = useLinkMetaFields(link);
  const [err, setErr] = useState<string | null>(null);
  const noun = NOUN[link.kind];
  const id = `led-${link.kind}`;

  async function submit() {
    setErr(null);
    if (f.costBad) return;
    try {
      await save.mutateAsync({ kind: link.kind, of_id: link.ofId, ...f.payload() });
      onClose();
    } catch (e) {
      setErr(errMsg(e, "Unable to save. Try again later"));
    }
  }

  // HB's modal at 480 (the editor pop-up, Tracking links #69 to #76).
  return (
    <HbModal
      title={`Edit ${noun}`}
      width={480}
      onClose={onClose}
      className="text-left whitespace-normal"
      footer={(
        <>
          <HbButton variant="secondary" onClick={onClose}>Cancel</HbButton>
          <HbButton onClick={() => void submit()} disabled={save.isPending || f.costBad}>Save</HbButton>
        </>
      )}
    >
      <form className="flex flex-col gap-6 text-fg" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <div className="flex flex-col gap-2">
          <FieldLabel htmlFor={`${id}-name`} text={`${noun[0].toUpperCase()}${noun.slice(1)} name`} />
          {/* Infloww's name field is disabled on edit. */}
          <Input id={`${id}-name`} className="h-9" value={link.name} disabled readOnly />
        </div>
        <LinkMetaFields f={f} id={id} accountId={accountId} sources={sources} tags={tagOptions} />
      </form>
      {err && <div className="mt-4 text-err text-xs" role="alert">{err}</div>}
    </HbModal>
  );
}

export function LinkBatchEditDialog({ accountId, kind, ofIds, sources, tags: tagOptions, onClose }: {
  accountId: string | null;
  kind: EditableKind;
  ofIds: number[];
  sources: string[];
  tags: string[];
  /** `saved`: the batch was stored (the caller drops the picks). */
  onClose: (saved?: boolean) => void;
}) {
  const save = useSaveLinkMetaBatch(accountId);
  const f = useLinkMetaFields();
  const [err, setErr] = useState<string | null>(null);
  const id = `lbe-${kind}`;
  const n = ofIds.length;

  async function submit() {
    setErr(null);
    if (f.costBad) return;
    const p = f.payload();
    const body: LinkMetaBatchBody = { kind, of_ids: ofIds };
    if (p.promo_cost != null) body.promo_cost = p.promo_cost;
    if (p.source) body.source = p.source;
    if (p.tags.length) body.tags = p.tags;
    if (Object.keys(body).length === 2) { setErr("Fill in Source, Promo cost or Tag"); return; }
    try {
      await save.mutateAsync(body);
      onClose(true);
    } catch (e) {
      setErr(errMsg(e, "Unable to save. Try again later"));
    }
  }

  return (
    <HbModal
      title="Batch edit"
      width={480}
      onClose={() => onClose()}
      className="text-left whitespace-normal"
      footer={(
        <>
          <HbButton variant="secondary" onClick={() => onClose()}>Cancel</HbButton>
          <HbButton onClick={() => void submit()} disabled={save.isPending || f.costBad || n === 0}>Save</HbButton>
        </>
      )}
    >
      <form className="flex flex-col gap-6 text-fg" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <div className="text-sm text-fg-dim">
          {n} {NOUN[kind]}{n === 1 ? "" : "s"} picked. A field filled in replaces that field on every one; one left
          empty stays as each link has it.
        </div>
        <LinkMetaFields f={f} id={id} accountId={accountId} sources={sources} tags={tagOptions} noList />
      </form>
      {err && <div className="mt-4 text-err text-xs" role="alert">{err}</div>}
    </HbModal>
  );
}
