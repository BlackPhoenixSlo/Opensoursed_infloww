import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { VaultMedia } from "@/lib/relay";

import { EMPTY_DRAFT } from "./composerDraft";
import {
  NO_OFFERS, clearRefusedOffers, dismissRefusedOffer, dispatchRefusedOffers, heldPreviews, readRefusedOffers,
  isOfferHere, offerRefusedSchedule, previewsDroppedBy, previewsFreedBy, refusedOffersReducer, revokeUnlessHeld,
  type RefusedOffer, type RefusedOffersAction, type RefusedOffersState,
} from "./refusedOffers";

const media = (id: number, preview?: string): VaultMedia => ({ id, type: "photo", _localPreview: preview });

function offer(text: string, attached: VaultMedia[] = [], fanId: number | string = 1): Omit<RefusedOffer, "id"> {
  return {
    text, draft: { ...EMPTY_DRAFT, attached, price: "5" },
    accountId: "a", fanId, fanName: "Fan", why: "relay said no",
  };
}

const run = (s: RefusedOffersState, as: RefusedOffersAction[]) => as.reduce(refusedOffersReducer, s);
const A = offer("one", [media(1, "blob:1"), media(2, "blob:2")]);
const B = offer("two", [media(2, "blob:2"), media(3, "blob:3")], 2);
const TWO = run(NO_OFFERS, [{ type: "refused", offer: A, epoch: 0 }, { type: "refused", offer: B, epoch: 0 }]);

describe("refusedOffersReducer", () => {
  it.each<[string, RefusedOffersAction[], string[], number]>([
    ["refused offers each, in order, with new ids", [], ["one", "two"], 3],
    ["removed drops that one", [{ type: "removed", id: 1 }], ["two"], 3],
    ["an id gone already changes nothing", [{ type: "removed", id: 1 }, { type: "removed", id: 1 }], ["two"], 3],
    ["ids are never reused", [{ type: "removed", id: 2 }, { type: "refused", offer: B, epoch: 0 }], ["one", "two"], 4],
    ["cleared drops all, ids go on", [{ type: "cleared" }], [], 3],
    ["a refusal from before an identity switch is dropped",
      [{ type: "cleared" }, { type: "refused", offer: A, epoch: 0 }], [], 3],
    ["one sent after it is offered", [{ type: "cleared" }, { type: "refused", offer: A, epoch: 1 }], ["one"], 4],
  ])("%s", (_name, actions, texts, nextId) => {
    const s = run(TWO, actions);
    expect(s.offers.map((o) => o.text)).toEqual(texts);
    expect(s.nextId).toBe(nextId);
  });

  it("keeps the whole draft", () => {
    expect(TWO.offers[0]).toMatchObject({ id: 1, ...A });
  });

  it("returns the same state when nothing changes", () => {
    expect(refusedOffersReducer(TWO, { type: "removed", id: 99 })).toBe(TWO);
    expect(refusedOffersReducer(TWO, { type: "refused", offer: A, epoch: 5 })).toBe(TWO);
  });

  it("cleared bumps the epoch even with nothing held", () => {
    expect(refusedOffersReducer(NO_OFFERS, { type: "cleared" }).epoch).toBe(1);
  });
});

describe("isOfferHere", () => {
  it.each<[string, string | null, number | string, boolean]>([
    ["same chat", "a", 1, true],
    ["same Fan, id as a string", "a", "1", true],
    ["another Fan", "a", 2, false],
    ["another Creator", "b", 1, false],
  ])("%s", (_name, accountId, fanId, want) => {
    expect(isOfferHere(TWO.offers[0], accountId, fanId)).toBe(want);
  });
});

describe("previews", () => {
  it("held: every offer's", () => {
    expect([...heldPreviews(TWO)].sort()).toEqual(["blob:1", "blob:2", "blob:3"]);
  });

  it.each<[string, number, Array<string | undefined>, string[]]>([
    ["dismissing frees those no other offer shows", 1, [], ["blob:1"]],
    ["nor the Composer's tiles", 1, ["blob:1"], []],
    ["the other offer", 2, [undefined], ["blob:3"]],
    ["an unknown id frees nothing", 9, [], []],
  ])("%s", (_name, id, shown, want) => {
    expect(previewsFreedBy(TWO, id, shown)).toEqual(want);
  });
});

describe("previewsDroppedBy", () => {
  const C = offer("three", [media(4, "blob:4"), media(5)]);
  const D = offer("four", [media(2, "blob:2"), media(6, "blob:6"), media(7, "blob:7")]);
  it.each<[string, RefusedOffersState, RefusedOffersAction, Array<string | undefined>, string[]]>([
    ["a stale refusal drops its previews", run(TWO, [{ type: "cleared" }]), { type: "refused", offer: C, epoch: 0 },
      [], ["blob:4"]],
    ["but those a held offer or the tiles still show", { ...TWO, epoch: 1 }, { type: "refused", offer: D, epoch: 0 },
      ["blob:7", undefined], ["blob:6"]],
    ["one of this epoch is offered: none", TWO, { type: "refused", offer: C, epoch: 0 }, [], []],
    ["other actions drop none here", TWO, { type: "removed", id: 1 }, [], []],
  ])("%s", (_n, s, a, shown, want) => {
    expect(previewsDroppedBy(s, a, shown)).toEqual(want);
  });
});

describe("the module's store", () => {
  let revoke: ReturnType<typeof vi.fn<(url: string) => void>>;
  beforeEach(() => {
    clearRefusedOffers();
    revoke = vi.fn<(url: string) => void>();
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(revoke);
    dispatchRefusedOffers({ type: "refused", offer: A, epoch: readRefusedOffers().epoch });
    dispatchRefusedOffers({ type: "refused", offer: B, epoch: readRefusedOffers().epoch });
  });
  afterEach(() => vi.restoreAllMocks());
  const revoked = () => revoke.mock.calls.map((c) => c[0]).sort();

  it("clearRefusedOffers (an identity switch) drops every offer and revokes the previews they held", () => {
    clearRefusedOffers();
    expect(readRefusedOffers().offers).toEqual([]);
    expect(revoked()).toEqual(["blob:1", "blob:2", "blob:3"]);
  });

  it("dismissRefusedOffer drops it and revokes what nothing else shows", () => {
    const [first] = readRefusedOffers().offers;
    expect(dismissRefusedOffer(first, [])).toEqual(["blob:1"]);
    expect(readRefusedOffers().offers.map((o) => o.text)).toEqual(["two"]);
    expect(revoked()).toEqual(["blob:1"]);
  });

  it.each<[string, boolean, Array<string | undefined>, string[], string[]]>([
    ["offerRefusedSchedule: a stale one is dropped, its previews revoked but those still shown or held",
      true, ["blob:7"], ["blob:6"], ["one", "two"]],
    ["offerRefusedSchedule: a current one is offered, nothing revoked", false, [], [], ["one", "two", "three"]],
  ])("%s", (_n, stale, shown, want, texts) => {
    const epoch = readRefusedOffers().epoch - (stale ? 1 : 0);
    const C = offer("three", [media(2, "blob:2"), media(6, "blob:6"), media(7, "blob:7")]);
    expect(offerRefusedSchedule(C, epoch, shown)).toEqual(want);
    expect(revoked()).toEqual(want);
    expect(readRefusedOffers().offers.map((o) => o.text)).toEqual(texts);
  });

  it("revokeUnlessHeld keeps what a held offer shows", () => {
    revokeUnlessHeld(["blob:2", "blob:9", undefined]);
    expect(revoked()).toEqual(["blob:9"]);
  });
});
