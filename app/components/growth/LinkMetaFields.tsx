"use client";

/**
 * LinkMetaFields — the fields Infloww's link editor (`LinkEditorFormContent`, index.9f50f370.js @14007983) puts under
 * the name: Source, Promo cost, Tag and List. One definition for the Edit dialog (`LinkEditDialog`) and the Create
 * tracking link pop-up, so the two cannot drift.
 *
 * Source, Promo cost and Tag are kept by the relay (`PUT /admin/link-meta`, or the create's own body) and never
 * written to OnlyFans. Source and Tag are free text with the account's values in use as suggestions; Infloww requires
 * a Source, ours is optional, so a link can carry a cost without one.
 *
 * List is OnlyFans' own "Add to list" on the link's claimers (`POST /lists/{id}/users/campaign/{id}/claimers` for a
 * tracking link, `/users/trial/{id}/claims` for a free trial link, both captured live): the relay adds every fan who
 * claimed the link to the picked list, in the background. Fans who claim later are added when the link's figures are
 * next read from OnlyFans: the relay's hourly pre-warm, or the page opened. OnlyFans adds nobody twice.
 * The options are every custom list of the account (`useFanLists` pages past 50). Changing or clearing the List does
 * not take fans out of the old one, and the select says so once it differs from the stored List (Infloww's
 * "Editing the list will not affect already-added fans"; the Edit dialog's Save is the confirm).
 */

import { useState } from "react";
import { X } from "lucide-react";

import { Button, Input } from "@/components/ui/primitives";
import { useFanLists } from "@/components/audience/fanLists";
import { PROMO_COST_MAX_LENGTH, formatPromoCost, parsePromoCost, promoCostText } from "@/components/growth/linkMetrics";
import { cn } from "@/lib/utils";

const FIELD = "h-9 w-full bg-bg border border-border rounded-lg px-3 text-sm disabled:opacity-50 disabled:cursor-not-allowed";
const TEXT_MAX = 100;   // Infloww's "Source name" and "Tag name" inputs
const TAGS_MAX = 20;
/** The relay's cap on a stored list name. */
export const LIST_NAME_MAX = 64;

export function FieldLabel({ htmlFor, text, optional }: { htmlFor: string; text: string; optional?: boolean }) {
  return (
    <label htmlFor={htmlFor} className="text-base">
      {optional ? <>{text} <span className="ml-1 text-sm text-fg-dim">Optional</span></> : text}
    </label>
  );
}

/** A Create whose OnlyFans reply had no link id: the link exists, but the fields could not be kept for it. */
export const META_LOST = "Link created; Source, Promo cost, Tag and List weren't saved. Use Edit.";

/** A link's stored fields, as the relay's reads carry them. */
export interface LinkMetaValues {
  promo_cost_cents?: number | null;
  link_source?: string | null;
  tags?: string[];
  list_id?: string | null;
  list_name?: string | null;
}

/** What the relay stores: `PUT /admin/link-meta`'s fields, and the create's. */
export interface LinkMetaPayload {
  promo_cost: number | null;
  source: string | null;
  tags: string[];
  list_id: string | null;
  list_name: string | null;
}

export type LinkMetaState = ReturnType<typeof useLinkMetaFields>;

/** The fields' state, seeded from a link's stored values (none for a new link). */
export function useLinkMetaFields(initial: LinkMetaValues = {}) {
  const [source, setSource] = useState(initial.link_source ?? "");
  const [cost, setCost] = useState(promoCostText(initial.promo_cost_cents));
  const [tags, setTags] = useState<string[]>(initial.tags ?? []);
  const [tag, setTag] = useState("");
  const [list, setList] = useState<{ id: string; name: string } | null>(
    initial.list_id ? { id: initial.list_id, name: initial.list_name ?? "" } : null,
  );
  // The List the link feeds now (none for a new link): what a change or a clear is told against.
  const [storedListId] = useState<string | null>(initial.list_id || null);
  const costValue = parsePromoCost(cost);
  const costBad = costValue != null && Number.isNaN(costValue);

  function addTag(raw: string) {
    const t = raw.trim().slice(0, TEXT_MAX);
    if (t && tags.length < TAGS_MAX && !tags.some((x) => x.toLowerCase() === t.toLowerCase())) setTags([...tags, t]);
    setTag("");
  }

  /** The body to send; a tag typed but not added yet is meant, so it is kept. */
  function payload(): LinkMetaPayload {
    const typed = tag.trim();
    const all = typed && !tags.some((x) => x.toLowerCase() === typed.toLowerCase())
      ? [...tags, typed].slice(0, TAGS_MAX) : tags;
    return {
      promo_cost: costValue, source: source.trim() || null, tags: all,
      list_id: list?.id ?? null, list_name: list ? list.name.slice(0, LIST_NAME_MAX) || null : null,
    };
  }

  /** Something beyond the name was filled in (the Create pop-up says when OnlyFans' reply lost it). */
  function filled(): boolean {
    const p = payload();
    return p.promo_cost != null || !!p.source || p.tags.length > 0 || !!p.list_id;
  }

  return {
    source, setSource, cost, setCost, tags, setTags, tag, setTag, list, setList, storedListId,
    costBad, addTag, payload, filled,
  };
}

/** Source, Promo cost, Tag and List, 24px apart as the editor's form lays them out (the caller's flex gap). */
export default function LinkMetaFields({ f, id, accountId, sources, tags: tagOptions, noList }: {
  f: LinkMetaState;
  /** The fields' id prefix: `${id}-source`, `${id}-cost`, `${id}-tag`, `${id}-list`. */
  id: string;
  accountId: string | null;
  /** The account's Sources and Tags in use: the inputs' suggestions. */
  sources: string[];
  tags: string[];
  /** Batch edit: no List (it adds fans on OnlyFans, one link at a time). */
  noList?: boolean;
}) {
  const { customLists, isLoading } = useFanLists(noList ? null : accountId);
  // OnlyFans' add-to-list takes a custom list's number; the built-ins (named ids) are not offered.
  const lists = customLists
    .filter((l) => /^\d+$/.test(String(l.id)))
    .map((l) => ({ id: String(l.id), name: l.name ?? `List ${l.id}` }));
  // A stored List no longer in OnlyFans' answer (deleted on OnlyFans, or the read failed) still shows.
  if (f.list && !lists.some((l) => l.id === f.list!.id)) lists.unshift({ id: f.list.id, name: f.list.name || `List ${f.list.id}` });

  return (
    <>
      <div className="flex flex-col gap-2">
        <FieldLabel htmlFor={`${id}-source`} text="Source" optional />
        <Input
          id={`${id}-source`}
          className="h-9"
          list={`${id}-sources`}
          placeholder="Source name"
          maxLength={TEXT_MAX}
          value={f.source}
          onChange={(e) => f.setSource(e.target.value)}
        />
        <datalist id={`${id}-sources`}>{sources.map((s) => <option key={s} value={s} />)}</datalist>
      </div>
      <div className="flex flex-col gap-2">
        <FieldLabel htmlFor={`${id}-cost`} text="Promo cost" optional />
        {/* A "$" prefix, 11 characters (Infloww's `PromoCostField`). */}
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-fg-dim" aria-hidden>$</span>
          <input
            id={`${id}-cost`}
            type="text"
            inputMode="decimal"
            maxLength={PROMO_COST_MAX_LENGTH}
            value={f.cost}
            aria-invalid={f.costBad || undefined}
            onChange={(e) => f.setCost(e.target.value)}
            onBlur={() => f.setCost(formatPromoCost(f.cost))}
            className={cn(FIELD, "pl-6", f.costBad && "border-err")}
          />
        </div>
        {f.costBad && <div className="text-err text-xs">Enter an amount up to 99,999,999.99</div>}
        <div className="text-xs text-fg-dim">Kept here for Profit, CPC, CPS and ROI; not sent to OnlyFans.</div>
      </div>
      <div className="flex flex-col gap-2">
        <FieldLabel htmlFor={`${id}-tag`} text="Tag" optional />
        {f.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5" aria-label="Tags">
            {f.tags.map((t) => (
              <span key={t} className="inline-flex items-center gap-1 rounded-md bg-bg-elev-2 px-2 py-0.5 text-xs">
                {t}
                <button type="button" aria-label={`Remove tag ${t}`} onClick={() => f.setTags(f.tags.filter((x) => x !== t))}>
                  <X size={12} aria-hidden />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <Input
            id={`${id}-tag`}
            className="h-9 flex-1"
            list={`${id}-tags`}
            placeholder="Tag name"
            maxLength={TEXT_MAX}
            value={f.tag}
            disabled={f.tags.length >= TAGS_MAX}
            onChange={(e) => f.setTag(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); f.addTag(f.tag); } }}
          />
          <Button type="button" variant="secondary" className="h-9" disabled={!f.tag.trim()} onClick={() => f.addTag(f.tag)}>
            Add tag
          </Button>
        </div>
        <datalist id={`${id}-tags`}>
          {tagOptions.filter((t) => !f.tags.includes(t)).map((t) => <option key={t} value={t} />)}
        </datalist>
      </div>
      {!noList && <div className="flex flex-col gap-2">
        <FieldLabel htmlFor={`${id}-list`} text="List" optional />
        <select
          id={`${id}-list`}
          className={FIELD}
          value={f.list?.id ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            f.setList(v ? { id: v, name: lists.find((l) => l.id === v)?.name ?? "" } : null);
          }}
        >
          <option value="">{isLoading ? "Loading lists…" : "None"}</option>
          {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        <ListNote stored={f.storedListId} picked={f.list?.id ?? null} />
      </div>}
    </>
  );
}

/** The List's helper text: what is added now, and when later claimers are. */
export const LIST_HELP =
  "Adds the link's fans to this OnlyFans list now. Fans who claim later are added when its figures are next read " +
  "from OnlyFans, about every hour. Changing it leaves fans already added in the old list.";

/** Under the List select: what saving will do. A new link or no stored List: what List does. A different list
 *  than the stored one, or None over it: what happens to the fans already added (Infloww's Modify / Delete copy). */
function ListNote({ stored, picked }: { stored: string | null; picked: string | null }) {
  if (stored && picked && picked !== stored) {
    return <div role="status" className="text-xs text-warn">Editing the list will not affect already-added fans.</div>;
  }
  if (stored && !picked) {
    return (
      <div role="status" className="text-xs text-warn">
        Once deleted, new subscribers will not be added to the list. Fans already added stay in it.
      </div>
    );
  }
  return (
    <div className="text-xs text-fg-dim">
      {LIST_HELP}
    </div>
  );
}
