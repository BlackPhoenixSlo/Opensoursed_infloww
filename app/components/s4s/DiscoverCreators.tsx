"use client";


import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";

import { EmptyState, IfButton, IfInput, IfModal } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";
import { ExtraTag } from "@/components/ui/primitives";
import { IF_DATE_FIELD, IfDateInput } from "@/components/ui/ifDateInput";
import { cn } from "@/lib/utils";
import { ProjectionAvatar, S4SMediaCarousel, message } from "@/components/s4s/s4sBits";
import {
  S4S_BLOCKS_KEY, S4S_REQUESTS_KEY, blockS4SCreator, proposeS4SSlot, s4sMediaUrl, sendS4SRequest, unblockS4SCreator,
  useS4SBlocks, useS4SDiscover,
  type S4SDiscoveryItem, type S4SMedia, type S4SProfile,
} from "@/lib/s4s";
import { BRAND_NAME } from "@/lib/brand";

export const EMPTY_LINE =
  "No other creator is listed yet. A creator appears here once it takes part in Share for Share, is allowed on "
  + "Discover Creators, and has a Primary post.";
export const DEPLOYMENT_LINE = `Your agency's other creators and other agencies' creators on this ${BRAND_NAME} deployment appear here.`;
const LOAD_ERROR = "The creator list failed to load due to network connection, please try again later.";

function EmptyText({ title, line }: { title: string; line: string }) {
  return (
    <>
      <span className="block text-[16px] font-semibold text-fg">{title}</span>
      <span className="mt-1 block text-[12px] font-semibold text-muted">{line}</span>
    </>
  );
}

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

const fromUtcInput = (v: string) => new Date(`${v}:00Z`);
const toUtcInput = (iso: string) => new Date(iso).toISOString().slice(0, 16);

function useProposedTime(fromAccountId: string | null, toProfileId: number) {
  const [when, setWhen] = useState("");
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
                <IfDateInput aria-label="Proposed time" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className={cn(IF_DATE_FIELD, "w-[220px]")} />
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

function PostThumb({ media = [] }: { media?: S4SMedia[] }) {
  const [broken, setBroken] = useState(false);
  const m = media[0];
  if (!m || broken) return null;
  return (
    <span className="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-bg-elev-1">
      {/* eslint-disable-next-line @next/next/no-img-element -- a Relay-served still, not a Next asset */}
      <img src={s4sMediaUrl(m.id)} alt={`${media.length > 1 ? `1 of ${media.length}, ` : ""}S4S ${m.media_type}`}
        loading="lazy" decoding="async" // each still is a live read on its Creator's session
        onError={() => setBroken(true)} className="h-full w-full object-cover" />
      {m.media_type === "video" && (
        <span aria-hidden className="absolute inset-0 grid place-items-center">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-black/50 text-white"><Play className="h-3 w-3" /></span>
        </span>
      )}
    </span>
  );
}

function CreatorCard({ item, onOpen }: { item: S4SDiscoveryItem; onOpen: () => void }) {
  return (
    <article aria-label={item.display_name}
      className="relative rounded-lg border border-border transition-colors hover:border-accent">
      <button type="button" onClick={onOpen} className="w-full p-4 text-left">
        <div className="flex items-center gap-3 pr-24">
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
        <div className="mt-3 flex items-start gap-3">
          <div className="flex h-[50px] w-[68px] shrink-0 flex-col items-center justify-center rounded-lg bg-bg-elev-1">
            <span className="text-[16px] font-medium text-fg">{item.daily_limit}</span>
            <span className="text-[10px] text-[#999]">Daily limit</span>
          </div>
          <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-[14px] text-fg-dim line-clamp-3">{item.primary_caption}</p>
          <PostThumb media={item.primary_media} />
        </div>
      </button>
      <IfButton className="absolute right-4 top-4" onClick={onOpen}>Request</IfButton>
    </article>
  );
}

export default function DiscoverCreators({ from }: { from: S4SProfile | null }) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<S4SDiscoveryItem | null>(null);
  const q = useS4SDiscover(filter);
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
      {q.isPending && (
        <div role="status" aria-label="Loading" className="grid grid-cols-1 items-start gap-4 px-6 pb-6 md:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-36 w-full rounded-lg" />)}
        </div>
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
