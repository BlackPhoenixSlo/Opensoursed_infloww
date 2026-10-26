"use client";

/**
 * Discover creators (Inventory §3.6; docs/spec/phase-03-share-for-share.md, UI; ADR-0011), on Infloww's
 * `DiscoverList` (page-parity 15): the 24px search row, then a two-column list of cards (`.dis-item`: 16px, 1px L1,
 * radius 8, hover M1). One card per opted-in, visible Creator with a Primary post on this Deployment, the owner's own
 * other Creators included and tagged "Your agency"; the creator picked on the rail is left out (it cannot send to
 * itself). A card shows the S4S projection and nothing else: the 44px avatar, display name, @username, a Daily
 * limit tile (in place of Infloww's stat tiles, which we have no figures for) and the Primary post's caption. A card
 * click opens the request pop-up (850), Infloww's layout: the Primary post's media carousel on the left; the avatar,
 * name, @username, tags (Daily limit in place of Infloww's VIP / ranking / Active Fans, which we have no figures for)
 * and "<name>'s S4S post" caption on the right. The request goes from the creator picked on the rail, at a proposed
 * time, as `POST /admin/s4s/requests`; the Relay decides every refusal and the pop-up shows its reason.
 * Not built, not faked: Filters (the projection has no account type or gender), Report, account-type tags.
 *
 * Another Agency's pop-up carries "Block": the Creator leaves this Agency's Discovery, and no request goes either way
 * between it and this Agency's Creators. The "Blocked creators" list under the cards lifts a block.
 *
 * ASSUMPTION: the empty-state line is decided on the unfiltered list only; a filter that matches nothing shows
 * Infloww's "No creators available" / "Try searching another keyword", because a filtered list says nothing about
 * other Creators' opt-ins. Rung 5.
 *
 * ASSUMPTION: the filter is sent to the Relay as `q` on every change, with no debounce. Rung 5 (the list is at most
 * 200 rows of one indexed table). Overturned if typing makes too many requests.
 *
 * The proposed time is picked in UTC (Infloww's S4S pages are in UTC) and sent as UTC. It is prefilled with the
 * Relay's proposal (`GET /admin/s4s/requests/proposal`): 06:00 UTC on the first day from tomorrow with room under
 * both Daily limits. Picking another rail creator re-proposes; an edit made while a proposal loads wins over it, and a
 * failed proposal leaves the field as it was.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { EmptyState, IfButton, IfInput, IfModal } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { ProjectionAvatar, S4SMediaCarousel, message } from "@/components/s4s/s4sBits";
import {
  S4S_BLOCKS_KEY, S4S_REQUESTS_KEY, blockS4SCreator, proposeS4SSlot, sendS4SRequest, unblockS4SCreator, useS4SBlocks,
  useS4SDiscover,
  type S4SDiscoveryItem, type S4SProfile,
} from "@/lib/s4s";
import { BRAND_NAME } from "@/lib/brand";

export const EMPTY_LINE =
  "No other creator is listed yet. A creator appears here once it takes part in Share for Share, is allowed on "
  + "Discover Creators, and has a Primary post.";
/** The Bounded S4S labelled improvement (ADR-0011): said under the search, never Infloww's community directory. */
export const DEPLOYMENT_LINE = `Your agency's other creators and other agencies' creators on this ${BRAND_NAME} deployment appear here.`;
const LOAD_ERROR = "The creator list failed to load due to network connection, please try again later.";

/** Two lines: Infloww's 16 / 600 title over its 12 / 600 T3 sentence. */
function EmptyText({ title, line }: { title: string; line: string }) {
  return (
    <>
      <span className="block text-[16px] font-semibold text-fg">{title}</span>
      <span className="mt-1 block text-[12px] font-semibold text-muted">{line}</span>
    </>
  );
}

/** Why the rail's creator can't send to `item`, or null when it can. */
function cannotSend(from: S4SProfile | null): string | null {
  const name = from?.display_name || from?.account_id || "this creator";
  if (!from?.opted_in || !from.posts.some((p) => p.is_primary)) {
    return `Opt ${name} in under S4S settings, with a Primary post, to send a request.`;
  }
  return null;
}

function Tag({ children }: { children: ReactNode }) {
  return <span className="inline-flex h-5 items-center rounded border border-[#999] px-1.5 text-[12px] text-[#999]">{children}</span>;
}

/** "YYYY-MM-DDTHH:mm" read as UTC. */
const fromUtcInput = (v: string) => new Date(`${v}:00Z`);
/** An ISO-8601 UTC instant as the field's "YYYY-MM-DDTHH:mm". */
const toUtcInput = (iso: string) => new Date(iso).toISOString().slice(0, 16);

/** The proposed-time field, prefilled with the Relay's proposal for this pair, re-proposed when the sender changes. */
function useProposedTime(fromAccountId: string | null, toProfileId: number) {
  const [when, setWhen] = useState("");
  // The owner's edits so far: a proposal that loads after one is dropped.
  const edits = useRef(0);
  useEffect(() => {
    if (!fromAccountId) return;
    let live = true;
    const before = edits.current;
    proposeS4SSlot(fromAccountId, toProfileId).then(({ slot_at }) => {
      if (live && slot_at && edits.current === before) setWhen(toUtcInput(slot_at));
    }, () => {});
    return () => { live = false; };
  }, [fromAccountId, toProfileId]);
  const edit = (v: string) => {
    edits.current += 1;
    setWhen(v);
  };
  return [when, edit] as const;
}

/** Block or unblock one Creator, then refresh Discovery and the blocked list. */
function useBlockAction() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(call: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await call();
      await Promise.all([
        qc.invalidateQueries({ queryKey: S4S_BLOCKS_KEY }),
        qc.invalidateQueries({ queryKey: ["s4s", "discover"] }),
      ]);
      return true;
    } catch (e) {
      setError(message(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run };
}

function RequestModal({ item, from, onClose }: { item: S4SDiscoveryItem; from: S4SProfile | null; onClose: () => void }) {
  const qc = useQueryClient();
  const block = useBlockAction();
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refusal = cannotSend(from);
  const [when, setWhen] = useProposedTime(refusal ? null : from!.account_id, item.profile_id);

  async function send() {
    const at = fromUtcInput(when);
    if (!when || Number.isNaN(at.getTime())) {
      setError("Pick a date and time.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      await sendS4SRequest({ from_account_id: from!.account_id, to_profile_id: item.profile_id, slot_at: at.toISOString() });
      setDone(true);
      await qc.invalidateQueries({ queryKey: S4S_REQUESTS_KEY });
    } catch (e) {
      setError(message(e));
    } finally {
      setSending(false);
    }
  }

  return (
    <IfModal
      label={item.display_name}
      width={850}
      onClose={onClose}
      footer={(
        <>
          {!item.own_agency && (
            <IfButton className="mr-auto" disabled={block.busy}
              onClick={() => void block.run(() => blockS4SCreator(item.profile_id)).then((ok) => { if (ok) onClose(); })}>
              Block
            </IfButton>
          )}
          <IfButton onClick={onClose}>{done ? "Close" : "Cancel"}</IfButton>
          <IfButton variant="primary" disabled={done || sending || !!refusal || !when} onClick={() => void send()}>
            {done ? "Requested" : "Send request"}
          </IfButton>
        </>
      )}
    >
      <div className="flex flex-col gap-5 md:flex-row">
        <S4SMediaCarousel media={item.primary_media} className="h-[420px] w-full shrink-0 md:w-[340px]" />
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex items-center gap-3 pr-8">
            <ProjectionAvatar item={item} px={72} />
            <div className="min-w-0">
              <div className="truncate text-[18px] font-semibold text-fg">{item.display_name}</div>
              <div className="text-[14px] text-[#999]">@{item.username}</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {item.own_agency && <Tag>Your agency</Tag>}
                <Tag>Daily limit: {item.daily_limit} per day</Tag>
              </div>
            </div>
          </div>
          <div>
            <h3 className="text-[16px] font-semibold text-fg">{item.display_name}&apos;s S4S post</h3>
            <p className="mt-1 whitespace-pre-wrap break-words text-[14px] text-fg-dim">{item.primary_caption}</p>
          </div>
          <div className="mt-auto">
            {refusal ? (
              <p className="text-[14px] text-fg-dim">{refusal}</p>
            ) : done ? (
              <p role="status" className="text-[14px] text-fg">Request sent from {from?.display_name || from?.account_id}.</p>
            ) : (
              <label className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
                <span>Proposed time (UTC):</span>
                <IfInput aria-label="Proposed time" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className="w-[220px]" />
                <span className="text-fg-dim">from {from?.display_name || from?.account_id}</span>
              </label>
            )}
            {(error || block.error) && <p role="alert" className="mt-2 text-[12px] text-err">{error || block.error}</p>}
          </div>
        </div>
      </div>
    </IfModal>
  );
}

function CreatorCard({ item, onOpen }: { item: S4SDiscoveryItem; onOpen: () => void }) {
  return (
    <article aria-label={item.display_name}>
      <button type="button" onClick={onOpen}
        className="w-full rounded-lg border border-border p-4 text-left transition-colors hover:border-accent">
        <div className="flex items-center gap-3">
          <ProjectionAvatar item={item} px={44} round />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[16px] font-semibold text-fg">{item.display_name}</span>
              {item.own_agency && (
                <span className="inline-flex h-4 items-center rounded border border-[#999] px-1 text-[10px] text-[#999]">Your agency</span>
              )}
            </div>
            <div className="text-[14px] text-[#999]">@{item.username}</div>
          </div>
        </div>
        <div className="mt-3 flex gap-1.5">
          <div className="flex h-[50px] w-[68px] flex-col items-center justify-center rounded-lg bg-bg-elev-1">
            <span className="text-[16px] font-medium text-fg">{item.daily_limit}</span>
            <span className="text-[10px] text-[#999]">Daily limit</span>
          </div>
        </div>
        <p className="mt-3 whitespace-pre-wrap break-words text-[14px] text-fg-dim line-clamp-4">{item.primary_caption}</p>
      </button>
    </article>
  );
}

export default function DiscoverCreators({ from }: { from: S4SProfile | null }) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<S4SDiscoveryItem | null>(null);
  const q = useS4SDiscover(filter);
  // The rail's own creator is never a partner of itself.
  const items = (q.data ?? []).filter((i) => from?.profile_id == null || i.profile_id !== from.profile_id);
  const filtered = filter.trim() !== "";
  const settled = q.isSuccess && !q.isPlaceholderData;
  const noneListed = settled && !filtered && items.length === 0;

  return (
    <div>
      <div className="p-6">
        <IfInput search aria-label="Search by name or @username" placeholder="Search by name or @username" value={filter}
          onChange={(e) => setFilter(e.target.value)} className="h-10 w-full rounded-lg" />
        <p className="mt-2 flex items-center gap-2 text-[12px] text-[#999]">{DEPLOYMENT_LINE} <ExtraTag /></p>
      </div>
      {q.isError && (
        <EmptyState kind="error" className="py-16" text={LOAD_ERROR}
          action={<IfButton variant="primary" onClick={() => void q.refetch()}>Refresh</IfButton>} />
      )}
      {noneListed && (
        <EmptyState className="py-10" text={<EmptyText title="No creators available" line={EMPTY_LINE} />} />
      )}
      {settled && filtered && items.length === 0 && (
        <EmptyState kind="search" className="py-24" text={<EmptyText title="No creators available" line="Try searching another keyword" />} />
      )}
      {items.length > 0 && (
        <div className="grid grid-cols-1 items-start gap-4 px-6 pb-6 md:grid-cols-2">
          {items.map((item) => <CreatorCard key={item.profile_id} item={item} onOpen={() => setOpen(item)} />)}
        </div>
      )}
      <Blocked />
      {open && <RequestModal item={open} from={from} onClose={() => setOpen(null)} />}
    </div>
  );
}

function Blocked() {
  const q = useS4SBlocks();
  const block = useBlockAction();
  const items = q.data ?? [];
  if (items.length === 0 && !q.error) return null;
  return (
    <section aria-label="Blocked creators" className="space-y-2 px-6 pb-6">
      <h3 className="text-[14px] font-semibold text-fg">Blocked creators</h3>
      {q.error && <p role="alert" className="text-[12px] text-err">{message(q.error)}</p>}
      {items.map((b) => (
        <div key={b.profile_id} className="flex items-center gap-2 text-[14px] text-fg">
          <span>{b.display_name}</span>
          <span className="text-[12px] text-[#999]">@{b.username}</span>
          <IfButton className="ml-auto" disabled={block.busy}
            onClick={() => void block.run(() => unblockS4SCreator(b.profile_id))}>
            Unblock
          </IfButton>
        </div>
      ))}
      {block.error && <p role="alert" className="text-[12px] text-err">{block.error}</p>}
    </section>
  );
}
