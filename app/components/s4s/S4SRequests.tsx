"use client";

/**
 * Requests (Inventory §3.6; docs/spec/phase-03-share-for-share.md, UI and Contracts), on Infloww's `Index$6`
 * (page-parity 15), for the creator picked on the rail: "Latest request" shows its pending received requests one at a
 * time, "(i/N)", with Accept, Decline, Skip and View Schedule; Accept opens "Share for Share Scheduled!". Under it
 * "Your requests": Received and Sent tabs over a table (Creators, Request Date, Status, Operation) with "Review" on a
 * new received request and "Cancel" (behind Infloww's confirm) on a sent one, 10 a page. Every request shows the
 * Creators as the request stored them at send time, never a live read of the other Agency (ADR-0011). A skipped
 * request is gone from Received and still reads "Request Sent" under Sent (the Relay decides both). Times are UTC.
 * Ours: the proposed time line (our requests carry one), and both sides' media as the request snapshotted them: the
 * partner's that your Creator posts, and your own that they post, seen before Accept (ADR-0015).
 */

import Link from "next/link";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";

import { EmptyState, IF_TABLE, IfButton, IfModal, IfPager, IfTabs, type IfOption } from "@/components/ui/infloww";
import { ProjectionAvatar, S4SMediaStrip, message, utcDate, utcTime } from "@/components/s4s/s4sBits";
import {
  S4S_REQUESTS_KEY, actOnS4SRequest, useS4SRequests,
  type S4SMedia, type S4SProfile, type S4SRequest, type S4SRequestAction, type S4SRequestBox,
} from "@/lib/s4s";
import { cn } from "@/lib/utils";

const TABS: IfOption<S4SRequestBox>[] = [{ value: "received", label: "Received" }, { value: "sent", label: "Sent" }];
const PAGE = 10;
const BIG = "h-[50px] rounded-[10px] text-[16px]";
const OUTLINE = "border-accent text-accent";
export const CANCEL_CONFIRM =
  "Your request is waiting to be accepted by the creator, are you confirming that you want to cancel your request?";

/** Infloww's status words and `.request-status` colours. */
function statusOf(r: S4SRequest): { text: string; color?: string } {
  switch (r.status) {
    case "pending": return { text: r.box === "received" ? "New Request" : "Request Sent" };
    case "accepted": return { text: "Scheduled", color: "text-[#ffa15f]" };
    case "declined": return { text: "Declined", color: "text-[#ffa15f]" };
    case "cancelled": return { text: "Cancelled", color: "text-[#ff7c71]" };
    case "expired": return { text: "Expired", color: "text-[#ff7c71]" };
  }
}

const scheduleHref = (accountId: string) => `/share-for-share/schedule?creator=${encodeURIComponent(accountId)}`;

/** One action on a request, then the lists read again. */
function useAct() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function act(id: number, action: S4SRequestAction): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await actOnS4SRequest(id, action);
      await qc.invalidateQueries({ queryKey: S4S_REQUESTS_KEY });
      return true;
    } catch (e) {
      setError(message(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { act, busy, error };
}

export default function S4SRequests({ profile, accountId }: { profile: S4SProfile | null; accountId: string }) {
  const [box, setBox] = useState<S4SRequestBox>("received");
  const [scheduled, setScheduled] = useState<S4SRequest | null>(null);
  const [review, setReview] = useState<S4SRequest | null>(null);
  const pid = profile?.profile_id ?? null;

  return (
    <div className="p-6">
      <LatestRequest profileId={pid} accountId={accountId} onAccepted={setScheduled} />
      <section aria-label="Your requests" className="mt-8">
        <h2 className="text-[16px] font-medium text-fg">Your requests</h2>
        <IfTabs aria-label="Your requests" tabs={TABS} value={box} onChange={setBox} className="px-0" />
        <RequestTable key={box} box={box} profileId={pid} accountId={accountId} onReview={setReview} />
      </section>
      {review && (
        <IfModal title="Review request" width={560} onClose={() => setReview(null)}>
          <RequestDetail request={review} accountId={accountId}
            onDone={(r, accepted) => { setReview(null); if (accepted) setScheduled(r); }} />
        </IfModal>
      )}
      {scheduled && <ScheduledModal request={scheduled} accountId={accountId} onClose={() => setScheduled(null)} />}
    </div>
  );
}

/** The pending received requests for this creator's profile, one at a time. */
function LatestRequest({ profileId, accountId, onAccepted }: {
  profileId: number | null;
  accountId: string;
  onAccepted: (r: S4SRequest) => void;
}) {
  const q = useS4SRequests("received");
  const pending = (q.data ?? []).filter((r) => r.status === "pending" && profileId != null && r.to.profile_id === profileId);
  const [at, setAt] = useState(0);
  const i = Math.min(at, Math.max(0, pending.length - 1));
  const current = pending[i];

  return (
    <section aria-label="Latest request">
      <h2 className="flex items-center gap-[15px] text-[16px] font-medium text-fg">
        Latest request
        {pending.length > 0 && <span className="text-fg-dim">({i + 1}/{pending.length})</span>}
      </h2>
      <div className={cn("mt-4 w-full max-w-[500px] rounded-lg border border-border p-6", !current && "flex min-h-[337px] flex-col items-center justify-center text-center")}>
        {q.isError ? (
          <p role="alert" className="text-[14px] text-err">{message(q.error)}</p>
        ) : current ? (
          <RequestDetail key={current.id} request={current} accountId={accountId}
            onDone={(r, accepted) => { if (accepted) onAccepted(r); }}
            onSkip={() => setAt(i)} />
        ) : (
          <>
            <p className="text-[16px] font-semibold text-fg">You don’t have any new requests</p>
            <p className="mt-2 text-[14px] text-fg-dim">Share your link and invite Creators to Share for Share with you</p>
          </>
        )}
      </div>
    </section>
  );
}

/** A received request's partner block and Infloww's buttons: Accept, Decline, then Skip and View Schedule. */
function RequestDetail({ request: r, accountId, onDone, onSkip }: {
  request: S4SRequest;
  accountId: string;
  onDone: (r: S4SRequest, accepted: boolean) => void;
  onSkip?: () => void;
}) {
  const { act, busy, error } = useAct();
  const partner = r.from;
  const pending = r.status === "pending";
  async function run(action: S4SRequestAction) {
    if (await act(r.id, action)) {
      if (action === "skip") onSkip?.();
      onDone(r, action === "accept");
    }
  }
  return (
    <article aria-label={`Request from ${partner.display_name}`} className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <ProjectionAvatar item={partner} px={60} />
        <div className="min-w-0">
          <div className="text-[16px] font-semibold text-fg">{partner.display_name}</div>
          <div className="text-[14px] text-[#999]">@{partner.username}</div>
        </div>
      </div>
      <p className="whitespace-pre-wrap break-words text-[14px] text-fg-dim line-clamp-4">{partner.primary_caption}</p>
      <MediaGroup label="Your Creator posts" media={r.from_media} />
      <MediaGroup label="They post" media={r.to_media} />
      <p className="text-[12px] text-[#999]">{`Proposed for ${utcDate(r.slot_at)} ${utcTime(r.slot_at)} · to ${r.to.display_name}`}</p>
      {pending && (
        <div className="flex flex-col gap-2.5">
          <IfButton variant="primary" className={cn(BIG, "w-full")} disabled={busy} onClick={() => void run("accept")}>Accept</IfButton>
          <IfButton className={cn(BIG, "w-full")} disabled={busy} onClick={() => void run("decline")}>Decline</IfButton>
          <div className="flex gap-5">
            <IfButton className={cn(BIG, OUTLINE, "flex-1")} disabled={busy} onClick={() => void run("skip")}>Skip</IfButton>
            <Link href={scheduleHref(accountId)}
              className={cn(BIG, OUTLINE, "flex flex-1 items-center justify-center border hover:opacity-80")}>View Schedule</Link>
          </div>
        </div>
      )}
      {error && <p role="alert" className="text-[12px] text-err">{error}</p>}
    </article>
  );
}

function ScheduledModal({ request: r, accountId, onClose }: { request: S4SRequest; accountId: string; onClose: () => void }) {
  return (
    <IfModal title="Share for Share Scheduled!" onClose={onClose} width={520}>
      <div className="flex flex-col items-center gap-4 text-center">
        <CheckCircle2 aria-hidden className="h-20 w-20 text-[#2ad4ac]" />
        <p className="text-[24px] font-extrabold text-fg">Share for Share Scheduled!</p>
        <p className="text-[14px] text-fg-dim">{`Your posts will be published in UTC time zone on ${utcDate(r.slot_at)} at ${utcTime(r.slot_at)}`}</p>
        <IfButton variant="primary" className={cn(BIG, "w-[380px] max-w-full")} onClick={onClose}>Got It</IfButton>
        <p className="text-[12px] text-fg-dim">
          Your upcoming Share for Share’s can be viewed in{" "}
          <Link href={scheduleHref(accountId)} className="text-accent hover:text-accent-hover">S4S Schedule</Link>
        </p>
      </div>
    </IfModal>
  );
}

function RequestTable({ box, profileId, accountId, onReview }: {
  box: S4SRequestBox;
  profileId: number | null;
  accountId: string;
  onReview: (r: S4SRequest) => void;
}) {
  const q = useS4SRequests(box);
  const { act, busy, error } = useAct();
  const [page, setPage] = useState(1);
  const [cancel, setCancel] = useState<S4SRequest | null>(null);
  const mine = (q.data ?? []).filter((r) => profileId != null && (box === "received" ? r.to : r.from).profile_id === profileId);
  const pages = Math.max(1, Math.ceil(mine.length / PAGE));
  const current = Math.min(page, pages);
  const rows = mine.slice((current - 1) * PAGE, current * PAGE);

  return (
    <div className="mt-4 space-y-4">
      {q.isError && <p role="alert" className="text-[14px] text-err">{message(q.error)}</p>}
      {error && <p role="alert" className="text-[14px] text-err">{error}</p>}
      <div className="overflow-x-auto">
        <table aria-label={box === "received" ? "Received requests" : "Sent requests"} className={cn(IF_TABLE.table, "min-w-[640px]")}>
          <thead>
            <tr>
              {["Creators", "Request Date", "Status", "Operation"].map((h, i) => (
                <th key={h} className={cn(IF_TABLE.th, i < 3 && IF_TABLE.thDivider)}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {q.isSuccess && mine.length === 0 && (
              <tr>
                <td colSpan={4} className="py-10">
                  <EmptyState size="md" textClassName="text-[12px] text-[#666]"
                    text={box === "received" ? "You haven’t received any requests from other Creators" : "You haven’t sent any requests to other Creators"}
                    action={box === "sent" ? (
                      <Link href={`/share-for-share/discover-creators?creator=${encodeURIComponent(accountId)}`}
                        className="flex h-10 w-[250px] items-center justify-center rounded-[10px] bg-accent text-[14px] text-white hover:bg-accent-hover">
                        Discover Creators
                      </Link>
                    ) : undefined} />
                </td>
              </tr>
            )}
            {rows.map((r) => {
              const partner = box === "received" ? r.from : r.to;
              const status = statusOf(r);
              return (
                <tr key={r.id} className={IF_TABLE.row}>
                  <td className={IF_TABLE.td}>
                    <span className="flex items-center gap-3">
                      <ProjectionAvatar item={partner} px={40} />
                      <span className="min-w-0 max-w-[250px]">
                        <span className="block truncate text-[16px] font-medium text-fg">{partner.display_name}</span>
                        <span className="block truncate text-[12px] font-medium text-muted">@{partner.username}</span>
                      </span>
                    </span>
                  </td>
                  <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>{utcDate(r.created_at)}</td>
                  <td className={cn(IF_TABLE.td, status.color)}>{status.text}</td>
                  <td className={IF_TABLE.td}>
                    {r.status === "pending" && box === "received" && (
                      <IfButton variant="link" onClick={() => onReview(r)}>Review</IfButton>
                    )}
                    {r.status === "pending" && box === "sent" && (
                      <IfButton variant="link" disabled={busy} onClick={() => setCancel(r)}>Cancel</IfButton>
                    )}
                    {r.status === "accepted" && (
                      <Link href={scheduleHref(accountId)} className="text-accent hover:text-accent-hover">View Schedule</Link>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {mine.length > 0 && (
        <IfPager total={mine.length} noun={mine.length === 1 ? "record" : "records"} page={current} size={PAGE} onPage={setPage} />
      )}
      {cancel && (
        <IfModal title={CANCEL_CONFIRM} width={416} onClose={() => setCancel(null)} footer={(
          <>
            <IfButton onClick={() => setCancel(null)}>No</IfButton>
            <IfButton variant="primary" disabled={busy}
              onClick={async () => { const r = cancel; setCancel(null); await act(r.id, "cancel"); }}>Yes</IfButton>
          </>
        )} />
      )}
    </div>
  );
}

/** One side's snapshotted media, labelled; nothing when it has none. */
function MediaGroup({ label, media }: { label: string; media: S4SMedia[] }) {
  if (media.length === 0) return null;
  return (
    <div role="group" aria-label={label} className="flex items-center gap-2 text-[12px] text-[#999]">
      <span>{label}:</span>
      <S4SMediaStrip media={media} />
    </div>
  );
}
