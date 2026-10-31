"use client";

import { useState } from "react";

import { Input } from "@/components/ui/primitives";
import { HbButton, HbModal } from "@/components/ui/infloww";
import { errMsg } from "@/components/growth/_bits";
import LinkMetaFields, { FieldLabel, META_LOST, useLinkMetaFields } from "@/components/growth/LinkMetaFields";
import { useCreateOfTrackingLink } from "@/hooks/useGrowth";

/** "Create tracking link" (#69): name, Source, Promo cost, Tag, List (#74), then "Save" (#75). The name creates the
 *  link through the existing OnlyFans write for the Creator the filter picked; the other fields (`LinkMetaFields`,
 *  the Edit dialog's) ride in the same request and the relay stores them for the new link's id. OnlyFans' reply
 *  without an id: the link exists but the fields were not stored, and the pop-up says so instead of closing. */
export function CreateLinkModal({ accountId, taken, sources, tags, onClose }: {
  accountId: string | null;
  /** The live links' names: the bundle refuses a repeat (`linkNameRepeat`), so we check before calling OnlyFans. */
  taken: string[];
  /** The account's Sources and Tags in use: the inputs' suggestions. */
  sources: string[];
  tags: string[];
  onClose: () => void;
}) {
  const createM = useCreateOfTrackingLink(accountId);
  const f = useLinkMetaFields();
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [lost, setLost] = useState(false);

  async function save() {
    setErr(null);
    // #70: the bundle's required-field words.
    if (!name.trim()) { setErr("This is a required field"); return; }
    if (taken.includes(name.trim())) { setErr("This link name already exists. Enter a different one"); return; }
    if (f.costBad) return;
    const body = f.filled() ? { name: name.trim(), ...f.payload() } : { name: name.trim() };
    try {
      const out = await createM.mutateAsync(body);
      if (out?.meta_saved === false) { setLost(true); return; }
      onClose();
    } catch (e) { setErr(errMsg(e, "Create failed")); }
  }

  return (
    <HbModal
      title="Create tracking link"
      width={480}
      onClose={onClose}
      footer={lost ? (
        <HbButton onClick={onClose}>Close</HbButton>
      ) : (
        <>
          {/* The bundle's two-button footer, both 36px: Cancel, then "Save" (#75). */}
          <HbButton variant="secondary" onClick={onClose}>Cancel</HbButton>
          <HbButton onClick={save} disabled={createM.isPending || f.costBad}>Save</HbButton>
        </>
      )}
    >
      {lost ? (
        <div role="alert" className="text-sm text-fg">
          {META_LOST}
        </div>
      ) : (
        /* #76: 24px between fields, 8px inside each. */
        <form className="flex flex-col gap-6 text-fg" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor="tl-ed-name" text="Tracking link name" />
            <Input
              id="tl-ed-name"
              className="h-9"
              maxLength={100}
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {err && <div className="text-err text-xs">{err}</div>}
          </div>
          <LinkMetaFields f={f} id="tl-ed" accountId={accountId} sources={sources} tags={tags} />
        </form>
      )}
    </HbModal>
  );
}
