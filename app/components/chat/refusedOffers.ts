/**
 * refusedOffers — schedules the relay refused that the Composer could not
 * put straight back (`afterRefusedSchedule`): the chatter typed on since, or
 * left the chat while it was in flight. Each holds the only copy of its
 * whole draft (text, price, lock, media, previews, schedule, tags, GIFs),
 * so it stays until restored or dismissed, never timed out.
 *
 * Module-level, as `lib/sendStash` is: the Composer and its ChatSurface
 * remount per chat (MessagesPro keys ChatSurface by Creator and
 * Fan), so a refusal that lands after a chat switch has no mounted owner.
 * Every chat's Composer lists them; Restore is offered only in the chat the
 * offer came from, so its draft goes back where it was written.
 *
 * Only a Fan chat's Composer makes offers (the only kind there is:
 * ChatSurface always has its Fan), so each names its chat.
 *
 * The store owns its offers' blob previews: they stay alive while held
 * (`revokeUnlessHeld`), dismissing one revokes those nothing else shows
 * (`dismissRefusedOffer`). An identity switch drops them all and bumps the
 * `epoch` (`clearRefusedOffers`, from `clearIdentityMemory` in UserContext),
 * so a refusal of the previous identity's send landing after it is dropped.
 */

import { useSyncExternalStore } from "react";

import { revokePreviews } from "@/lib/blobPreviews";
import { sameUserId, type FanId } from "@/lib/fanId";

import type { FullDraft } from "./composerDraft";

/** A refused schedule's draft, its chat, and why the relay refused it. */
export interface RefusedOffer extends FullDraft {
  id: number;
  accountId: string | null;
  fanId: FanId;
  /** The Fan's name as the chat showed it, for the notice in other chats. */
  fanName: string | null;
  why: string;
}

export interface RefusedOffersState {
  offers: RefusedOffer[];
  nextId: number;
  /** Bumped by `cleared`: a send started before it is another identity's. */
  epoch: number;
}

export const NO_OFFERS: RefusedOffersState = { offers: [], nextId: 1, epoch: 0 };

export type RefusedOffersAction =
  /** A refusal nobody could put back: offered, in arrival order, unless
   *  its send started in an earlier `epoch` (before an identity switch). */
  | { type: "refused"; offer: Omit<RefusedOffer, "id">; epoch: number }
  /** Restored into its chat's Composer, or dismissed. */
  | { type: "removed"; id: number }
  /** Everything goes (an identity switch). */
  | { type: "cleared" };

export function refusedOffersReducer(s: RefusedOffersState, a: RefusedOffersAction): RefusedOffersState {
  switch (a.type) {
    case "refused":
      if (a.epoch !== s.epoch) return s;
      return { ...s, offers: [...s.offers, { ...a.offer, id: s.nextId }], nextId: s.nextId + 1 };
    case "removed":
      return s.offers.some((o) => o.id === a.id)
        ? { ...s, offers: s.offers.filter((o) => o.id !== a.id) }
        : s;
    case "cleared":
      return { ...s, offers: [], epoch: s.epoch + 1 };
  }
}

/** The offer was written in this chat (a Composer without a Fan has none). */
export function isOfferHere(o: RefusedOffer, accountId: string | null, fanId: FanId | null): boolean {
  return o.accountId === accountId && sameUserId(o.fanId, fanId);
}

/** Blob previews the held offers still show. */
export function heldPreviews(s: RefusedOffersState): Set<string> {
  const out = new Set<string>();
  for (const o of s.offers) for (const m of o.draft.attached) if (m._localPreview) out.add(m._localPreview);
  return out;
}

/** What dismissing `id` frees: its previews no other offer nor `shown` (the
 *  Composer's tiles) still shows. */
export function previewsFreedBy(s: RefusedOffersState, id: number, shown: Array<string | undefined>): string[] {
  const offer = s.offers.find((o) => o.id === id);
  if (!offer) return [];
  const kept = heldPreviews(refusedOffersReducer(s, { type: "removed", id }));
  shown.forEach((u) => u && kept.add(u));
  return offer.draft.attached.map((m) => m._localPreview).filter((u): u is string => !!u && !kept.has(u));
}

/* ── the module's one state ─────────────────────────────────────────────── */

let state: RefusedOffersState = NO_OFFERS;
const listeners = new Set<() => void>();

export function dispatchRefusedOffers(a: RefusedOffersAction): void {
  const next = refusedOffersReducer(state, a);
  if (next === state) return;
  state = next;
  listeners.forEach((l) => l());
}

export function readRefusedOffers(): RefusedOffersState {
  return state;
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Revoke `urls` but those a held offer still shows (a Composer's tiles
 *  going). */
export function revokeUnlessHeld(urls: Array<string | undefined>): void {
  const held = heldPreviews(state);
  revokePreviews(urls.filter((u) => !(u && held.has(u))));
}

/** Dismiss an offer and revoke its previews nothing else shows (`shown`: the
 *  Composer's tiles). Returns those revoked. */
export function dismissRefusedOffer(offer: RefusedOffer, shown: Array<string | undefined>): string[] {
  const gone = previewsFreedBy(state, offer.id, shown);
  dispatchRefusedOffers({ type: "removed", id: offer.id });
  revokePreviews(gone);
  return gone;
}

/** Drop every offer and revoke its previews (an identity switch: they are
 *  the previous identity's drafts). */
export function clearRefusedOffers(): void {
  const held = heldPreviews(state);
  dispatchRefusedOffers({ type: "cleared" });
  revokePreviews([...held]);
}

/** Every held offer, live. */
export function useRefusedOffers(): RefusedOffersState {
  return useSyncExternalStore(subscribe, readRefusedOffers, () => NO_OFFERS);
}
