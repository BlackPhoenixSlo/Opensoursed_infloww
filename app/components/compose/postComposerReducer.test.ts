import { describe, expect, it } from "vitest";

import type { PickedTemplate } from "@/components/chat/TemplatePicker";
import type { FanOutResult } from "@/components/compose/fanOut";
import {
  buildPostBody, initPostForm, postComposerReducer, postFieldAction, postPrice, validatePost,
  type PostAction, type PostForm,
} from "@/components/compose/postComposerReducer";
import type { VaultMedia } from "@/lib/relay";

const run = (s: PostForm, ...actions: PostAction[]) => actions.reduce(postComposerReducer, s);
const media = (id: number) => ({ id, type: "photo" }) as VaultMedia;
const form = (over: Partial<PostForm> = {}): PostForm => ({ ...initPostForm(), accountId: "acc1", text: "hi", ...over });
const tpl = (over: Partial<PickedTemplate> = {}): PickedTemplate => ({
  source: "local", text: "t", displayText: "t", mediaCount: 0, price: 0, lockedText: false,
  isWelcome: false, media: [], previews: [], taggedUsers: [], ...over,
});
const tag = { id: 1, name: "a", username: "a", avatar: null };
const ok = (accountId: string): FanOutResult => ({ accountId, ok: true });
const bad = (accountId: string): FanOutResult => ({ accountId, ok: false, error: "500" });
const paid = form({ price: "10", previewCount: 1, attached: [media(1)], taggedCreators: [tag] });

describe("postComposerReducer", () => {
  it.each<[string, PostForm, PostAction[], Partial<PostForm>]>([
    ["all-models on keeps the form, the account too (the rest is derived, not cleared)", paid,
      [{ type: "setAllModels", on: true }],
      { allModels: true, accountId: "acc1", price: "10", previewCount: 1, attached: [media(1)] }],
    ["BUG: all-models on → off is back on the account with its media, previews and tags (was: re-seeded, cleared)", paid,
      [{ type: "setAllModels", on: true }, { type: "setAllModels", on: false }],
      { allModels: false, accountId: "acc1", text: "hi", attached: [media(1)], previewCount: 1, taggedCreators: [tag] }],
    ["BUG: account switch drops the old account's media, previews and tags", paid,
      [{ type: "setAccount", id: "acc2" }],
      { accountId: "acc2", attached: [], previewCount: 0, taggedCreators: [], price: "10", text: "hi" }],
    ["BUG: the first pick (null → A) is no switch: nothing dropped", { ...paid, accountId: null },
      [{ type: "setAccount", id: "acc2" }],
      { accountId: "acc2", attached: [media(1)], previewCount: 1, taggedCreators: [tag] }],
    ["BUG: leaving all-models clears the fan-out results (were: shown on one account)",
      form({ allModels: true, results: [bad("a")] }), [{ type: "setAllModels", on: false }],
      { allModels: false, results: null }],
    ["BUG: a FREE template clears a typed price (was: kept the old PPV)", form({ price: "25" }),
      [{ type: "pickTemplate", t: tpl() }], { price: "", text: "t" }],
    ["a paid template sets its price, media and preview count", form(),
      [{ type: "pickTemplate", t: tpl({ price: 7, media: [media(4)], previews: [4] }) }],
      { price: "7", previewCount: 1, attached: [media(4)] }],
    ["a free template after a paid one replaces previewCount and media", form(),
      [{ type: "pickTemplate", t: tpl({ price: 7, media: [media(4), media(5)], previews: [4] }) },
        { type: "pickTemplate", t: tpl({ media: [media(6)] }) }],
      { price: "", previewCount: 0, attached: [media(6)] }],
    ["field sets one input", form(), [postFieldAction("schedule", "x")], { schedule: "x" }],
    ["BUG: appendText appends to the CURRENT text (emoji, no cursor)", form(),
      [postFieldAction("text", "a"), { type: "appendText", v: "🙂" }, { type: "appendText", v: "!" }], { text: "a🙂!" }],
    ["progress is {done,total}", form(),
      [{ type: "progress", done: 1, total: 3 }], { progress: { done: 1, total: 3 } }],
    ["results land and clear progress", form(),
      [{ type: "progress", done: 2, total: 2 }, { type: "results", v: [ok("a"), bad("b")] }],
      { progress: null, results: [ok("a"), bad("b")] }],
    ["BUG: a retry's results merge by account (were: replaced, or cleared on send)", form(),
      [{ type: "results", v: [ok("a"), bad("b"), bad("c")] }, { type: "results", v: [ok("b"), bad("c")] }],
      { results: [ok("a"), ok("b"), bad("c")] }],
  ])("%s", (_n, start, actions, want) => {
    expect(run(start, ...actions)).toMatchObject(want);
  });

  it.each<[string, PostForm, PostAction]>([
    ["all-models re-asserted", form({ allModels: true, accountId: null }), { type: "setAllModels", on: true }],
    ["same account", form(), { type: "setAccount", id: "acc1" }],
    ["same field value", form(), postFieldAction("text", "hi")],
  ])("no-op returns the same state: %s", (_n, s, a) => {
    expect(postComposerReducer(s, a)).toBe(s);
  });

  // #13-1: after a partial fan-out an edit would reach only the failed models
  // (the posted ones keep the old post), so the content is locked until Start over.
  const partial = form({ allModels: true, results: [ok("a"), bad("b")] });
  it.each<[string, PostAction]>([
    ["text", postFieldAction("text", "edited")],
    ["emoji", { type: "appendText", v: "!" }],
    ["media", postFieldAction("attached", [media(2)])],
    ["price", postFieldAction("price", "9")],
    ["previews", postFieldAction("previewCount", 1)],
    ["schedule", postFieldAction("schedule", "2030-01-01T10:00")],
    ["tags", postFieldAction("taggedCreators", [tag])],
    ["template", { type: "pickTemplate", t: tpl({ text: "other" }) }],
    ["account", { type: "setAccount", id: "acc2" }],
    ["all-models off (would clear the results, re-arming a post to all)", { type: "setAllModels", on: false }],
  ])("BUG: a partial fan-out locks the content: %s is refused", (_n, a) => {
    expect(postComposerReducer(partial, a)).toBe(partial);
  });
  // A round in flight (progress set, round 1: no results yet): its body is
  // built, so an edit would show content it doesn't send, and all-models off
  // would land its results in one-account mode.
  const inFlight = form({ allModels: true, progress: { done: 0, total: 2 } });
  it.each<[string, PostAction]>([
    ["text", postFieldAction("text", "edited")],
    ["emoji", { type: "appendText", v: "!" }],
    ["template", { type: "pickTemplate", t: tpl({ text: "other" }) }],
    ["all-models off", { type: "setAllModels", on: false }],
  ])("BUG: a round in flight locks the content: %s is refused", (_n, a) => {
    expect(postComposerReducer(inFlight, a)).toBe(inFlight);
  });
  it("BUG: Start over is refused while a retry is in flight (its successes would be forgotten)", () => {
    const retrying = { ...partial, progress: { done: 0, total: 1 } };
    expect(postComposerReducer(retrying, { type: "discardResults" })).toBe(retrying);
    expect(run(retrying, { type: "discardResults" }, { type: "results", v: [ok("b")] }).results)
      .toEqual([ok("a"), ok("b")]);
  });
  it.each<[string, PostForm, PostAction[], Partial<PostForm>]>([
    ["the retry's lifecycle still runs", partial,
      [{ type: "progress", done: 0, total: 1 }, { type: "results", v: [ok("b")] }],
      { results: [ok("a"), ok("b")], progress: null, text: "hi" }],
    ["Start over unlocks: results cleared, then an edit lands", partial,
      [{ type: "discardResults" }, postFieldAction("text", "edited")], { results: null, text: "edited" }],
    ["every model failed: nothing went out, so no lock", form({ allModels: true, results: [bad("a"), bad("b")] }),
      [postFieldAction("text", "edited")], { text: "edited" }],
  ])("%s", (_n, start, actions, want) => {
    expect(run(start, ...actions)).toMatchObject(want);
  });

  it("a template keeps the post's own fields (no lockedText / pickedGifs)", () => {
    const s = postComposerReducer(form(), { type: "pickTemplate", t: tpl({ price: 7, lockedText: true }) });
    expect(s).not.toHaveProperty("lockedText");
    expect(s).not.toHaveProperty("pickedGifs");
  });
});

describe("validatePost — the one check (button, mutation)", () => {
  it.each<[string, Partial<PostForm>, number, boolean, string | null]>([
    ["a ready text post", {}, 2, false, null],
    ["no account", { accountId: null }, 2, false, "Pick an account"],
    ["all-models with no model", { allModels: true, accountId: null }, 0, false, "No models picked for broadcast"],
    ["BUG: the last failed model excluded after a round (was: No models picked)",
      { allModels: true, results: [ok("a"), bad("b")] }, 0, false, "Nothing to retry: every failed model is excluded"],
    ["all-models text-only", { allModels: true, accountId: null }, 2, false, null],
    ["BUG: all-models with a price typed after (text-only: price ignored)", { allModels: true, accountId: null, price: "5" }, 2, false, null],
    ["all-models with hidden media + price + tags", { allModels: true, accountId: null, price: "5", attached: [media(1)], taggedCreators: [tag] }, 2, false, null],
    ["BUG: all-models with media and no text says Add text (media can't be added there)", { allModels: true, accountId: null, text: "", attached: [media(1)] }, 2, false, "Add text"],
    ["all-models with an unparsable hidden price", { allModels: true, accountId: null, price: "abc" }, 2, false, null],
    ["paid with no media", { price: "5" }, 2, false, "A paid post needs at least one image"],
    ["paid with media", { price: "5", attached: [media(1)] }, 2, false, null],
    ["invalid price", { price: "abc" }, 2, false, "Invalid price"],
    ["invalid price on a subscription page (not counted)", { price: "abc" }, 2, true, null],
    ["paid on a subscription page, no media", { price: "5" }, 2, true, null],
    ["empty", { text: " " }, 2, false, "Add text or media"],
    ["media only", { text: "", attached: [media(1)] }, 2, false, null],
    ["invalid schedule", { schedule: "nope" }, 2, false, "Invalid schedule date"],
  ])("%s", (_n, over, broadcastCount, paidPage, want) => {
    expect(validatePost(form(over), { broadcastCount, paidPage })).toBe(want);
  });
});

describe("postPrice — always finite, 0 where the price doesn't count", () => {
  it.each<[Partial<PostForm>, boolean, number]>([
    [{ price: "7" }, false, 7],
    [{ price: "7" }, true, 0],
    [{ price: "7", allModels: true }, false, 0],
    [{ price: "" }, false, 0],
    [{ price: "abc" }, false, 0],
    [{ price: "." }, false, 0],
  ])("%o paidPage=%s → %s", (over, paidPage, want) => {
    expect(postPrice(form(over), paidPage)).toBe(want);
  });
});

describe("buildPostBody — the one body", () => {
  const iso = (local: string) => new Date(local).toISOString();
  it.each<[string, PostForm, boolean, Record<string, unknown>]>([
    ["free text post", form({ text: " hi " }), false, { text: "hi", media_files: [], price: 0, posted_at: null }],
    ["paid post carries leading preview ids and tags",
      form({ price: "9", previewCount: 1, attached: [media(5), media(6)], taggedCreators: [tag], schedule: "2030-01-01T10:00" }), false,
      { text: "hi", media_files: [5, 6], price: 9, posted_at: iso("2030-01-01T10:00"), previews: [5], tagged_users: [1] }],
    ["a free post carries no previews", form({ previewCount: 1, attached: [media(5)] }), false,
      { text: "hi", media_files: [5], price: 0, posted_at: null }],
    ["a fresh upload sends its claim", form({ attached: [{ ...media(0), _claim: { k: 1 } }] }), false,
      { text: "hi", media_files: [{ k: 1 }], price: 0, posted_at: null }],
    ["BUG: all-models is text-only — price 0, no media, previews or tags", { ...paid, allModels: true, accountId: null }, false,
      { text: "hi", media_files: [], price: 0, posted_at: null }],
    ["subscription page: price 0, no previews (media kept)", paid, true,
      { text: "hi", media_files: [1], price: 0, posted_at: null, tagged_users: [1] }],
  ])("%s", (_n, f, paidPage, want) => {
    expect(buildPostBody(f, paidPage)).toEqual(want);
  });

  it.each<[string, PostForm]>([
    ["paid text-only template", postComposerReducer(form(), { type: "pickTemplate", t: tpl({ text: "tpl", price: 12 }) })],
    ["paid template with media + previews",
      postComposerReducer(form(), { type: "pickTemplate", t: tpl({ text: "tpl", price: 12, media: [media(4), media(5)], previews: [4] }) })],
    ["price typed before the page was known", form({ price: "9", previewCount: 1, attached: [media(4)] })],
  ])("subscription page, %s → valid and free; a normal page keeps the price", (_n, f) => {
    expect(f.price).not.toBe("");
    expect(validatePost(f, { broadcastCount: 2, paidPage: true })).toBeNull();
    expect(buildPostBody(f, true)).toMatchObject({ price: 0 });
    expect(buildPostBody(f, true)).not.toHaveProperty("previews");
    expect(buildPostBody(f, false).price).toBeGreaterThan(0);
  });
});
