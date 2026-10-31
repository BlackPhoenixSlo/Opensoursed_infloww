import { describe, expect, it } from "vitest";

import type { PickedTemplate } from "@/components/chat/TemplatePicker";
import { buildSendArgs, canBeFreePreview as chatCanBeFreePreview, EMPTY_DRAFT } from "@/components/chat/composerDraft";
import { applyTemplate, canBeFreePreview, previewIdsFor, type ComposeDraft } from "@/lib/composeDraft";
import type { VaultMedia } from "@/lib/relay";

const media = (id: number) => ({ id, type: "photo" }) as VaultMedia;

function tpl(over: Partial<PickedTemplate> = {}): PickedTemplate {
  return {
    source: "local", text: "tpl text", displayText: "tpl text", mediaCount: 0,
    price: 0, lockedText: false, isWelcome: false, media: [], previews: [], taggedUsers: [],
    ...over,
  };
}

/** A paid draft with a GIF picked and a lock on — what a template replaces. */
const dirty: Required<ComposeDraft> = {
  text: "old", attached: [media(1)], price: "25", previewCount: 1, lockedText: true,
  taggedCreators: [{ id: 7, name: "seven", username: "s", avatar: null }],
  pickedGifs: [{ id: "g-old", thumbUrl: "u", fullUrl: "u" }],
};

describe("applyTemplate", () => {
  it.each([
    // [name, template, expected price, lockedText]
    ["a FREE template clears a typed price and the lock", tpl(), "", false],
    ["a paid template sets its price, lock off", tpl({ price: 12 }), "12", false],
    ["a paid template sets its price and its lock", tpl({ price: 12, lockedText: true }), "12", true],
    ["a free template ignores a lock it carries", tpl({ lockedText: true }), "", false],
  ])("%s", (_name, t, price, lockedText) => {
    const next = applyTemplate(dirty, t);
    expect(next.price).toBe(price);
    expect(next.lockedText).toBe(lockedText);
  });

  it.each([
    ["a template without a GIF clears picked GIFs", tpl(), []],
    ["a GIF template seeds its GIF", tpl({ gifId: "g1", gifUrl: "http://g", title: "T" }),
      [{ id: "g1", thumbUrl: "http://g", fullUrl: "http://g", title: "T" }]],
  ])("%s", (_name, t, gifs) => {
    expect(applyTemplate(dirty, t).pickedGifs).toEqual(gifs);
  });

  it("replaces text, attachments and preview count wholesale (0 previews overwrites)", () => {
    const next = applyTemplate(dirty, tpl({ media: [media(5), media(6)], previews: [] }));
    expect(next.text).toBe("tpl text");
    expect(next.attached.map((m) => m.id)).toEqual([5, 6]);
    expect(next.previewCount).toBe(0);
    expect(applyTemplate(dirty, tpl({ media: [media(5)], previews: [5] })).previewCount).toBe(1);
  });

  it("merges tagged creators by id, keeping the ones already there", () => {
    const next = applyTemplate(dirty, tpl({ taggedUsers: [7, 8] }));
    expect(next.taggedCreators.map((c) => c.id)).toEqual([7, 8]);
    expect(next.taggedCreators[1]).toEqual({ id: 8, name: "user8", username: "", avatar: null });
    expect(applyTemplate(dirty, tpl()).taggedCreators).toBe(dirty.taggedCreators);
  });

  it("leaves fields a composer lacks absent (a post has no lock / GIFs)", () => {
    const post: ComposeDraft = { text: "", attached: [], price: "9", previewCount: 0, taggedCreators: [] };
    const next = applyTemplate(post, tpl({ gifId: "g1", lockedText: true, price: 3 }));
    expect("lockedText" in next).toBe(false);
    expect("pickedGifs" in next).toBe(false);
    expect(next.price).toBe("3");
    expect(applyTemplate(post, tpl()).price).toBe("");
  });

  it("keeps the composer's own fields", () => {
    const next = applyTemplate({ ...dirty, schedule: "x" }, tpl());
    expect(next.schedule).toBe("x");
  });
});

describe("previewIdsFor / canBeFreePreview — the one free-preview rule", () => {
  const v = (id: number, claim?: Record<string, unknown>) => ({ id, type: "photo", ...(claim ? { _claim: claim } : {}) }) as VaultMedia;
  const claim = { processId: "p" };
  it.each<[string, VaultMedia[], number, number, number[]]>([
    ["free send carries none", [v(1), v(2), v(3)], 2, 0, []],
    ["count 0 carries none", [v(1), v(2), v(3)], 0, 10, []],
    ["leading count ids on a paid send", [v(1), v(2), v(3)], 2, 10, [1, 2]],
    ["count past the end takes all", [v(1), v(2)], 5, 10, [1, 2]],
    ["claims and non-positive ids drop out", [v(0, claim), v(0), v(4), v(5)], 3, 10, [4]],
    ["a claim on a real id drops out (still transcoding)", [v(7, claim), v(8)], 2, 10, [8]],
    ["NaN price is free", [v(1)], 1, Number.NaN, []],
  ])("%s", (_name, media, count, price, want) => {
    expect(previewIdsFor(media, count, price)).toEqual(want);
  });
  it.each<[string, VaultMedia, boolean]>([
    ["a vault id", v(3), true],
    ["a fresh upload's claim", v(3, claim), false],
    ["no id", v(0), false],
    ["NaN id", v(Number.NaN), false],
  ])("canBeFreePreview: %s", (_n, m, want) => {
    expect(canBeFreePreview(m)).toBe(want);
  });
  // Both call shapes read the one rule: the chat Composer's (`buildSendArgs`,
  // and PpvTiles' FREE badge via chat/composerDraft's re-export) and the mass
  // / post composers' (`previewIdsFor`).
  it("chat/composerDraft re-exports this predicate, not a copy", () => {
    expect(chatCanBeFreePreview).toBe(canBeFreePreview);
  });
  it.each<[string, VaultMedia[], number]>([
    ["vault ids", [v(1), v(2), v(3)], 2],
    ["a claim and a bad id among them", [v(0, claim), v(4), v(-1), v(5)], 3],
    ["a claim on a real id", [v(7, claim), v(8)], 2],
  ])("buildSendArgs' previews == previewIdsFor: %s", (_n, attached, count) => {
    const args = buildSendArgs({ ...EMPTY_DRAFT, attached, price: "10", previewCount: count }, { text: "x", now: 0 });
    expect(args.previews).toEqual(previewIdsFor(attached, count, 10));
  });
});
