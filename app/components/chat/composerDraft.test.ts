import { describe, expect, it } from "vitest";

import type { VaultMedia } from "@/lib/relay";
import { PRICE_NOTE } from "@/lib/sendGuards";

import {
  EMPTY_DRAFT, FAILED_UPLOAD_NOTE, afterRefusedSchedule, buildSendArgs, canSend, composerDraft, composerView,
  effectivePreviewCount, isEmptyDraft, isScheduling, richText, sendBlockedReason, sentReplyId,
  type ComposerDraft, type DraftAction, type SendCtx, type ViewCtx,
} from "./composerDraft";
import type { PickedTemplate } from "./TemplatePicker";

const media = (id: number, extra: Partial<VaultMedia> = {}): VaultMedia => ({ id, type: "photo", ...extra });
const tpl = (over: Partial<PickedTemplate> = {}): PickedTemplate => ({
  source: "local", text: "hi", displayText: "hi", mediaCount: 0, price: 0, lockedText: false,
  isWelcome: false, media: [], previews: [], taggedUsers: [], ...over,
});
const gif = (id: string) => ({ id, thumbUrl: `t/${id}`, fullUrl: `f/${id}` });
const tag = (id: number) => ({ id, name: `n${id}`, username: `u${id}`, avatar: null });
const draft = (over: Partial<ComposerDraft> = {}): ComposerDraft => ({ ...EMPTY_DRAFT, ...over });
const run = (s: ComposerDraft, ...as: DraftAction[]) => as.reduce(composerDraft, s);

const NOW = new Date("2026-10-29T12:00:00").getTime();
const LATER = "2026-10-29T13:00"; // datetime-local, an hour ahead
const EARLIER = "2026-10-29T11:00";
const ctx = (over: Partial<SendCtx> = {}): SendCtx => ({
  text: "hey", chatCanSend: true, uploading: false, uploadFailed: false, now: NOW, ...over,
});

// A PPV draft with everything the PPV row lists, plus tags and a Script step.
const STEP = { scriptId: "s1", scriptStep: 2 };
const FULL = draft({
  price: "12", priceOpen: true, lockedText: true, attached: [media(1), media(2)], previewCount: 1,
  scheduleOpen: true, scheduleAt: LATER, taggedCreators: [tag(7)], pickedGifs: [gif("g1")], script: STEP,
  rich: { html: "<p><em>hey</em></p>", plain: "hey" }, mode: { toolbar: true, rich: true }, replyId: 42,
});

describe("composerDraft", () => {
  it.each<[string, ComposerDraft, DraftAction[], Partial<ComposerDraft>]>([
    ["setPrice sanitizes", EMPTY_DRAFT, [{ type: "setPrice", raw: "1a2,5.0" }], { price: "12.50" }],
    ["setPriceOpen", EMPTY_DRAFT, [{ type: "setPriceOpen", open: true }], { priceOpen: true }],
    ["setLockText", EMPTY_DRAFT, [{ type: "setLockText", on: true }], { lockedText: true }],
    ["stepPreviews +", draft({ attached: [media(1), media(2)] }), [{ type: "stepPreviews", by: 1 }], { previewCount: 1 }],
    ["stepPreviews + stops at the tiles", draft({ attached: [media(1)], previewCount: 1 }),
      [{ type: "stepPreviews", by: 1 }], { previewCount: 1 }],
    ["stepPreviews − stops at 0", draft({ attached: [media(1)] }), [{ type: "stepPreviews", by: -1 }], { previewCount: 0 }],
    // 4 stored, 1 tile left: the stepper shows 1/1, so − goes to 0 (it went to 3, still showing 1).
    ["remove a tile then − steps from the count on show", draft({ attached: [media(1), media(2)], previewCount: 4 }),
      [{ type: "removeAttachment", id: 2 }, { type: "stepPreviews", by: -1 }], { attached: [media(1)], previewCount: 0 }],
    ["schedule open keeps the time", draft({ scheduleAt: LATER }), [{ type: "schedule", open: true }],
      { scheduleOpen: true, scheduleAt: LATER }],
    ["schedule at keeps it open", draft({ scheduleOpen: true }), [{ type: "schedule", at: LATER }],
      { scheduleOpen: true, scheduleAt: LATER }],
    ["addGif dedupes", draft({ pickedGifs: [gif("a")] }),
      [{ type: "addGif", gif: gif("a") }, { type: "addGif", gif: gif("b") }], { pickedGifs: [gif("a"), gif("b")] }],
    ["removeGif", draft({ pickedGifs: [gif("a"), gif("b")] }), [{ type: "removeGif", id: "a" }], { pickedGifs: [gif("b")] }],
    ["setTags", EMPTY_DRAFT, [{ type: "setTags", tags: [tag(1)] }], { taggedCreators: [tag(1)] }],
    ["removeAttachment", draft({ attached: [media(1), media(2)] }), [{ type: "removeAttachment", id: 1 }],
      { attached: [media(2)] }],
    ["uploaded skips ids already attached", draft({ attached: [media(1)] }),
      [{ type: "uploaded", media: [media(1, { type: "video" }), media(2)] }], { attached: [media(1), media(2)] }],
    ["reorder", draft({ attached: [media(1), media(2)] }), [{ type: "reorder", attached: [media(2), media(1)] }],
      { attached: [media(2), media(1)] }],
    ["clearPpv empties the row, keeps tags, the Script step and its markup", FULL, [{ type: "clearPpv" }],
      { ...EMPTY_DRAFT, taggedCreators: [tag(7)], script: STEP, rich: FULL.rich, mode: FULL.mode, replyId: 42 }],
    ["dropScript (the FM bubble's AI draft) forgets the Script step and its saved reply only", FULL,
      [{ type: "dropScript" }], { script: null, replyId: null }],
    ["sent empties everything, the Script step too; \"Aa\" stays on", FULL, [{ type: "sent" }],
      { ...EMPTY_DRAFT, mode: { toolbar: true, rich: true } }],
    ["restore is the snapshot", draft({ price: "3" }), [{ type: "restore", snapshot: FULL }], FULL],
  ])("%s", (_name, start, actions, want) => {
    expect(run(start, ...actions)).toEqual({ ...start, ...want });
  });

  it("sent clears lockedText, so the next PPV is not text-locked (it used to leak)", () => {
    const next = run(FULL, { type: "sent" }, { type: "setPrice", raw: "5" });
    expect(next.lockedText).toBe(false);
    expect(buildSendArgs(next, { text: "again", now: NOW }).lockedText).toBe(false);
  });

  it("restore puts the pre-send snapshot back, lockedText and the Script step included", () => {
    const back = run(FULL, { type: "sent" }, { type: "restore", snapshot: FULL });
    expect(back).toEqual(FULL);
    expect(back).toMatchObject({ lockedText: true, script: STEP });
  });

  describe("pickTemplate", () => {
    it("a paid template replaces media, price, lock, previews and GIF; its tags join", () => {
      const s = run(FULL, {
        type: "pickTemplate",
        t: tpl({ price: 9, lockedText: true, media: [media(5), media(6)], previews: [5], taggedUsers: [7, 8], gifId: "g9", gifUrl: "u9", title: "T" }),
        rich: true,
      });
      expect(s).toEqual({
        ...FULL,
        price: "9", priceOpen: true, lockedText: true, attached: [media(5), media(6)], previewCount: 1,
        taggedCreators: [tag(7), { id: 8, name: "user8", username: "", avatar: null }],
        pickedGifs: [{ id: "g9", thumbUrl: "u9", fullUrl: "u9", title: "T" }],
        script: null, // no Script on this template: the old step goes
        rich: null, // nor formatting: the old markup goes
        replyId: null, // nor a saved reply id (an OF row's shape): the old one goes
      });
    });
    it.each<[string, Partial<PickedTemplate>, ComposerDraft["script"]]>([
      ["a Script step", { scriptId: "s9", scriptStep: 3 }, { scriptId: "s9", scriptStep: 3 }],
      ["an FM step", { scriptId: "FM12", scriptStep: 0 }, { scriptId: "FM12", scriptStep: 0 }],
      ["no Script", {}, null],
      ["a Script with no step", { scriptId: "s9", scriptStep: null }, null],
    ])("%s sets the draft's script (a newer pick replaces an older one)", (_name, over, want) => {
      expect(run(FULL, { type: "pickTemplate", t: tpl(over) }).script).toEqual(want);
    });
    it("a free template clears a typed price, the lock and previews; a GIF-less one keeps the picked GIF", () => {
      const s = run(FULL, { type: "pickTemplate", t: tpl({ lockedText: true }) });
      expect(s).toMatchObject({ price: "", priceOpen: false, lockedText: false, attached: [], previewCount: 0, pickedGifs: FULL.pickedGifs });
      expect(s.taggedCreators).toBe(FULL.taggedCreators);
      expect(s.scheduleAt).toBe(LATER);
    });
  });

  describe("pickVault", () => {
    it("replaces the pick, keeps a transcoding upload and an upload's own files + preview", () => {
      const claim = media(-1, { _claim: { processId: "p" }, _localPreview: "blob:c" });
      const up = media(3, { _localPreview: "blob:3", files: { thumb: { url: "mine" } } as VaultMedia["files"] });
      const s = run(draft({ attached: [media(1), up, claim], price: "4" }), {
        type: "pickVault", picked: [media(2), media(3, { files: null })],
      });
      expect(s.attached).toEqual([media(2), up, claim]);
      expect(s.price).toBe("4"); // unpriced media leave the typed price alone
    });
    it("prices the bundle at its highest suggested price and opens the PPV row", () => {
      const priced = (id: number, cents: number | null) => media(id, { _ai: { suggested_price_cents: cents } });
      const s = run(draft({ price: "50" }), { type: "pickVault", picked: [priced(1, 799), priced(2, 1299), priced(3, null)] });
      expect(s).toMatchObject({ price: "12.99", priceOpen: true });
    });
  });
});

describe("effectivePreviewCount / isScheduling", () => {
  it.each([[3, 2, 2], [1, 2, 1], [-1, 2, 0], [2, 0, 0]])("previewCount %i of %i tiles → %i", (n, tiles, want) => {
    const attached = Array.from({ length: tiles }, (_, i) => media(i + 1));
    expect(effectivePreviewCount(draft({ previewCount: n, attached }))).toBe(want);
  });
  it.each<[Partial<ComposerDraft>, boolean]>([
    [{ scheduleOpen: true, scheduleAt: LATER }, true],
    [{ scheduleOpen: true, scheduleAt: EARLIER }, false],
    [{ scheduleOpen: true, scheduleAt: "" }, false],
    [{ scheduleOpen: true, scheduleAt: "garbage" }, false],
    [{ scheduleOpen: false, scheduleAt: LATER }, false],
  ])("%o scheduling=%s", (over, want) => {
    expect(isScheduling(draft(over), NOW)).toBe(want);
  });
});

describe("canSend / sendBlockedReason", () => {
  const SCHED = { scheduleOpen: true, scheduleAt: LATER };
  it.each<[string, Partial<ComposerDraft>, Partial<SendCtx>, boolean, string | null]>([
    ["plain text", {}, {}, true, null],
    ["nothing to send", {}, { text: "   " }, false, null],
    ["media only", { attached: [media(1)] }, { text: "" }, true, null],
    ["GIF only", { pickedGifs: [gif("a")] }, { text: "" }, true, null],
    ["upload only, sending now", {}, { text: "", uploading: true }, true, null],
    ["disabled", {}, { disabled: true }, false, null],
    ["OF blocks the chat", {}, { chatCanSend: false }, false, null],
    ["price under $3", { price: "2" }, {}, false, PRICE_NOTE],
    ["price 0 is free", { price: "0", priceOpen: true }, {}, true, null],
    ["failed upload", {}, { uploadFailed: true }, false, FAILED_UPLOAD_NOTE],
    ["uploading while scheduling", SCHED, { uploading: true }, false, "Wait for the upload to finish before scheduling"],
    ["failed upload while scheduling", SCHED, { uploading: true, uploadFailed: true }, false, FAILED_UPLOAD_NOTE],
    ["a past schedule sends now, upload and all", { scheduleOpen: true, scheduleAt: EARLIER }, { uploading: true }, true, null],
  ])("%s", (_name, over, c, want, reason) => {
    expect(sendBlockedReason(draft(over), ctx(c))).toBe(reason);
    expect(canSend(draft(over), ctx(c))).toBe(want);
  });
});

describe("buildSendArgs", () => {
  const claim = media(-1, { _claim: { processId: "p" } });
  it.each<[string, Partial<ComposerDraft>, { delayMinutes?: number }, ReturnType<typeof buildSendArgs>]>([
    ["text only", {}, {}, { text: "hey" }],
    ["free media (price 0)", { price: "0", attached: [media(1)], previewCount: 1, lockedText: true }, {},
      { text: "hey", attached: [media(1)] }],
    ["PPV with lock and no previews", { price: "9.5", lockedText: true, attached: [media(1)] }, {},
      { text: "hey", price: 9.5, lockedText: true, attached: [media(1)] }],
    ["PPV previews skip a transcoding upload", { price: "5", attached: [claim, media(2), media(3)], previewCount: 2 }, {},
      { text: "hey", price: 5, lockedText: false, previews: [2], attached: [claim, media(2), media(3)] }],
    ["previews clamp to the tiles", { price: "5", attached: [media(1)], previewCount: 4 }, {},
      { text: "hey", price: 5, lockedText: false, previews: [1], attached: [media(1)] }],
    ["tags and the first GIF", { taggedCreators: [tag(1), tag(2)], pickedGifs: [gif("a"), gif("b")] }, {},
      { text: "hey", taggedUsers: [1, 2], giphyId: "a" }],
    ["schedule ahead", { scheduleOpen: true, scheduleAt: LATER }, {},
      { text: "hey", scheduledAt: new Date(LATER).toISOString() }],
    ["schedule past sends now", { scheduleOpen: true, scheduleAt: EARLIER }, {}, { text: "hey" }],
    ["schedule closed ignores the time", { scheduleAt: LATER }, {}, { text: "hey" }],
    ["schedule garbage sends now", { scheduleOpen: true, scheduleAt: "garbage" }, {}, { text: "hey" }],
    ["Timed delay wins over the schedule", { scheduleOpen: true, scheduleAt: LATER }, { delayMinutes: 5 },
      { text: "hey", scheduledAt: new Date(NOW + 5 * 60_000).toISOString() }],
  ])("%s", (_name, over, opts, want) => {
    expect(buildSendArgs(draft(over), { text: "hey", now: NOW, ...opts })).toEqual(want);
  });
});

describe("sentReplyId: the saved reply a send counts for", () => {
  const picked = (over: Partial<PickedTemplate>) => run(FULL, { type: "pickTemplate", t: tpl(over) });
  it.each<[string, ComposerDraft, number | null]>([
    ["a picked saved reply", picked({ replyId: 7 }), 7],
    ["a sequence step", picked({ replyId: 8, scriptId: "Welcome", scriptStep: 2 }), 8],
    ["the OF welcome (no id)", picked({ source: "of" }), null],
    ["a typed message", EMPTY_DRAFT, null],
    ["after the send", run(picked({ replyId: 7 }), { type: "sent" }), null],
  ])("%s", (_n, d, want) => expect(sentReplyId(d)).toBe(want));
});

describe("a formatted script's markup (rich)", () => {
  const HTML = '<p><span class="m-editor-fc__blue-1"><strong>Hey</strong></span> babe</p>';
  const picked = (over: Partial<PickedTemplate> = {}, rich = true) =>
    run(EMPTY_DRAFT, { type: "pickTemplate", t: tpl(over), rich });
  it.each<[string, Partial<PickedTemplate>, ComposerDraft["rich"]]>([
    ["formatted script keeps its markup", { text: "Hey babe", displayText: HTML }, { html: HTML, plain: "Hey babe" }],
    ["plain script has none", { text: "hi", displayText: "hi" }, null],
    ["unformatted markup has none", { text: "hi", displayText: "<p>hi</p>" }, null],
  ])("pick: %s", (_n, t, want) => expect(picked(t).rich).toEqual(want));
  it.each<[string, boolean, string, ComposerDraft["rich"], ComposerDraft["mode"]]>([
    ["OF: formatted opens the rich editor with its markup", true, HTML, { html: HTML, plain: "Hey babe" }, { toolbar: false, rich: true }],
    ["Fansly: formatted goes in plain, no markup, no editor", false, HTML, null, { toolbar: false, rich: false }],
    ["OF: plain script stays in the textarea", true, "hi", null, { toolbar: false, rich: false }],
  ])("pick mode: %s", (_n, allowed, displayText, rich, mode) => {
    const s = picked({ text: "Hey babe", displayText }, allowed);
    expect([s.rich, s.mode]).toEqual([rich, mode]);
  });
  const R = { html: HTML, plain: "Hey babe" };
  it.each<[string, ComposerDraft, DraftAction[], ComposerDraft["mode"], ComposerDraft["rich"]]>([
    ["Aa on: toolbar + rich editor", EMPTY_DRAFT, [{ type: "aa" }], { toolbar: true, rich: true }, null],
    ["Aa off, no formatting: back to the textarea", EMPTY_DRAFT, [{ type: "aa" }, { type: "aa" }], { toolbar: false, rich: false }, null],
    ["Aa off, formatting kept (OF): toolbar hides, editor + markup stay", EMPTY_DRAFT,
      [{ type: "aa" }, { type: "setRich", rich: R }, { type: "aa" }], { toolbar: false, rich: true }, R],
    ["an edit dropping the formatting stays in the editor", draft({ rich: R, mode: { toolbar: false, rich: true } }),
      [{ type: "setRich", rich: null }], { toolbar: false, rich: true }, null],
    ["sent: the toolbar stays on, the box empties", EMPTY_DRAFT,
      [{ type: "aa" }, { type: "setRich", rich: R }, { type: "sent" }], { toolbar: true, rich: true }, null],
    ["sent with Aa off: back to the textarea", draft({ rich: R, mode: { toolbar: false, rich: true } }),
      [{ type: "sent" }], { toolbar: false, rich: false }, null],
  ])("mode: %s", (_n, start, actions, mode, rich) => {
    const s = run(start, ...actions);
    expect([s.mode, s.rich]).toEqual([mode, rich]);
  });
  it.each<[string, boolean | undefined, string]>([
    ["OF formatted sends markup", false, HTML],
    ["plainOnly (Fansly, a translation) sends plain", true, "Hey babe"],
  ])("buildSendArgs: %s", (_n, plainOnly, want) =>
    expect(buildSendArgs(draft({ rich: R }), { text: "Hey babe", now: NOW, plainOnly }).text).toBe(want));

  const d = draft({ rich: { html: HTML, plain: "Hey babe" } });
  it.each<[string, string, string | null]>([
    ["untouched sends the markup", "Hey babe", HTML],
    ["untouched modulo edge spaces", "  Hey babe ", HTML],
    ["edited falls back to plain", "Hey babe!", null],
  ])("send: %s", (_n, text, want) => {
    expect(richText(d, text)).toBe(want);
    expect(buildSendArgs(d, { text, now: NOW }).text).toBe(want ?? text);
  });
  it("no rich on a typed message", () => expect(richText(EMPTY_DRAFT, "x")).toBeNull());
  it("a draft holding a script's markup is not empty", () => expect(isEmptyDraft(d)).toBe(false));
});

describe("composerView", () => {
  const vctx = (over: Partial<ViewCtx> = {}): ViewCtx => ({ ...ctx(), uploadChips: 0, ...over });
  const TWO = [media(1), media(2)];
  it.each<[string, Partial<ComposerDraft>, Partial<ViewCtx>, Partial<ReturnType<typeof composerView>>]>([
    ["empty: row shut, nothing held", {}, {},
      { paid: null, priceLabel: "", ppvHeld: false, ppvRowOpen: false, held: false, scheduling: false, canSend: true }],
    ["the pill alone opens the row; the PPV pill can close it", { priceOpen: true }, {},
      { ppvHeld: false, ppvRowOpen: true, held: false }],
    ["media hold the row open and the Fan", { attached: TWO }, {}, { ppvHeld: true, ppvRowOpen: true, held: true }],
    ["a GIF holds both", { pickedGifs: [gif("a")] }, {}, { ppvHeld: true, held: true }],
    ["an upload chip holds both", {}, { uploadChips: 1 }, { ppvHeld: true, held: true }],
    ["schedule mode holds the row, not the Fan", { scheduleOpen: true }, {}, { ppvHeld: true, held: false }],
    ["price 0 is free", { price: "0", priceOpen: true }, {}, { paid: null, priceLabel: "", ppvHeld: false, held: false }],
    ["a paid price holds both and labels the tiles", { price: "5" }, {},
      { paid: 5, priceLabel: "$5", ppvHeld: true, held: true, priceError: null }],
    ["cents show two places", { price: "5.5" }, {}, { paid: 5.5, priceLabel: "$5.50" }],
    ["under $3 holds Send and the Timed message", { price: "2" }, {},
      { canSend: false, sendBlockedReason: PRICE_NOTE, priceError: PRICE_NOTE, timedBlockedReason: PRICE_NOTE }],
    ["the divider splits free from paid", { price: "5", attached: TWO, previewCount: 1 }, {},
      { previews: 1, showDivider: true }],
    ["no divider when every tile is free", { price: "5", attached: TWO, previewCount: 2 }, {},
      { previews: 2, showDivider: false }],
    ["no divider on a free send", { attached: TWO, previewCount: 1 }, {}, { showDivider: false }],
    ["previews clamp to the tiles", { price: "5", attached: TWO, previewCount: 4 }, {}, { previews: 2 }],
    ["scheduling labels Schedule", { scheduleOpen: true, scheduleAt: LATER }, {}, { scheduling: true }],
    ["a running upload holds the Timed message but not Send", {}, { uploading: true },
      { canSend: true, sendBlockedReason: null, timedBlockedReason: "Wait for the upload to finish before scheduling" }],
    ["a failed upload holds both", {}, { uploadFailed: true, uploadChips: 1 },
      { canSend: false, sendBlockedReason: FAILED_UPLOAD_NOTE, timedBlockedReason: FAILED_UPLOAD_NOTE }],
  ])("%s", (_name, over, c, want) => {
    expect(composerView(draft(over), vctx(c))).toMatchObject(want);
  });
});

describe("afterRefusedSchedule", () => {
  const typed = { text: "new", draft: EMPTY_DRAFT };
  const attachedSince = { text: "", draft: draft({ attached: [media(9)] }) };
  const pickedSince = { text: "", draft: draft({ script: { scriptId: "s2", scriptStep: 1 } }) };
  it.each<[string, { text: string; draft: ComposerDraft } | null, "restore" | "offer"]>([
    ["untouched since the send: the refused draft comes back", { text: "", draft: EMPTY_DRAFT }, "restore"],
    ["left the chat (no Composer): offered", null, "offer"],
    ["typed on since: their text stays, the refused one is offered", typed, "offer"],
    ["attached since: their media stay", attachedSince, "offer"],
    ["picked a Script step since: it stays (its media, price and step)", pickedSince, "offer"],
  ])("%s", (_name, now, want) => {
    expect(afterRefusedSchedule(now)).toBe(want);
  });
  it("only what `sent` leaves is empty: every draft field counts", () => {
    expect(isEmptyDraft(run(FULL, { type: "sent" }))).toBe(true);
    // `mode` is the box's look (rich editor or textarea), not content.
    for (const k of (Object.keys(EMPTY_DRAFT) as (keyof ComposerDraft)[]).filter((k) => k !== "mode")) {
      expect(FULL[k], k).not.toEqual(EMPTY_DRAFT[k]);
      expect(isEmptyDraft({ ...EMPTY_DRAFT, [k]: FULL[k] }), k).toBe(false);
    }
  });
});
