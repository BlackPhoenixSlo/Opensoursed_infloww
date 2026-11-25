import { useSyncExternalStore } from "react";

import { revokePreviews } from "@/lib/blobPreviews";
import { sameUserId, type FanId } from "@/lib/fanId";

import type { FullDraft } from "./composerDraft";

export interface RefusedOffer extends FullDraft {
  id: number;
  accountId: string | null;
  fanId: FanId;
  fanName: string | null;
  why: string;
}

export interface RefusedOffersState {
  offers: RefusedOffer[];
  nextId: number;
  epoch: number;
}

export const NO_OFFERS: RefusedOffersState = { offers: [], nextId: 1, epoch: 0 };

export type RefusedOffersAction =
  | { type: "refused"; offer: Omit<RefusedOffer, "id">; epoch: number }
  | { type: "removed"; id: number }
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

export function isOfferHere(o: RefusedOffer, accountId: string | null, fanId: FanId): boolean {
  return o.accountId === accountId && sameUserId(o.fanId, fanId);
}

export function heldPreviews(s: RefusedOffersState): Set<string> {
  const out = new Set<string>();
  for (const o of s.offers) for (const m of o.draft.attached) if (m._localPreview) out.add(m._localPreview);
  return out;
}

export function previewsFreedBy(s: RefusedOffersState, id: number, shown: Array<string | undefined>): string[] {
  const offer = s.offers.find((o) => o.id === id);
  if (!offer) return [];
  const kept = heldPreviews(refusedOffersReducer(s, { type: "removed", id }));
  shown.forEach((u) => u && kept.add(u));
  return offer.draft.attached.map((m) => m._localPreview).filter((u): u is string => !!u && !kept.has(u));
}

export function previewsDroppedBy(
  s: RefusedOffersState, a: RefusedOffersAction, shown: Array<string | undefined>,
): string[] {
  if (a.type !== "refused" || refusedOffersReducer(s, a) !== s) return [];
  const kept = heldPreviews(s);
  shown.forEach((u) => u && kept.add(u));
  return a.offer.draft.attached.map((m) => m._localPreview).filter((u): u is string => !!u && !kept.has(u));
}


// Module-level: Composer/ChatSurface remount per chat, so a refusal landing after a switch has no mounted owner; each offer holds the only copy of its draft.
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

export function revokeUnlessHeld(urls: Array<string | undefined>): void {
  const held = heldPreviews(state);
  revokePreviews(urls.filter((u) => !(u && held.has(u))));
}

export function dismissRefusedOffer(offer: RefusedOffer, shown: Array<string | undefined>): string[] {
  const gone = previewsFreedBy(state, offer.id, shown);
  dispatchRefusedOffers({ type: "removed", id: offer.id });
  revokePreviews(gone);
  return gone;
}

export function offerRefusedSchedule(
  offer: Omit<RefusedOffer, "id">, epoch: number, shown: Array<string | undefined>,
): string[] {
  const action: RefusedOffersAction = { type: "refused", offer, epoch };
  const gone = previewsDroppedBy(state, action, shown);
  dispatchRefusedOffers(action);
  revokePreviews(gone);
  return gone;
}

export function clearRefusedOffers(): void {
  const held = heldPreviews(state);
  dispatchRefusedOffers({ type: "cleared" });
  revokePreviews([...held]);
}

export function useRefusedOffers(): RefusedOffersState {
  return useSyncExternalStore(subscribe, readRefusedOffers, () => NO_OFFERS);
}
