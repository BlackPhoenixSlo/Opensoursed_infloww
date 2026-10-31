import { describe, expect, it } from "vitest";

import type { PickedTemplate } from "@/components/chat/TemplatePicker";
import {
  buildMassBody, confirmPrompt, fieldAction, gifNote, gifOnlyForm, initMassForm, MASS_ALREADY_SENT,
  MASS_ONE_GIF_ALL_MODELS, massMessageReducer, validateMass,
  type MassAction, type MassCtx, type MassForm,
} from "@/components/compose/massMessageReducer";
import type { TaggedCreatorChoice, VaultMedia } from "@/lib/relay";
import { PRICE_NOTE } from "@/lib/sendGuards";
import { SENSITIVE_BLOCK_MESSAGE } from "@/lib/sensitiveWords";

const run = (s: MassForm, ...actions: MassAction[]) => actions.reduce(massMessageReducer, s);
const sorted = <T,>(set: ReadonlySet<T>) => [...set].sort();
const media = (id: number, extra: Partial<VaultMedia> = {}) => ({ id, type: "photo", ...extra }) as VaultMedia;
const tag = (id: number): TaggedCreatorChoice => ({ id, name: `c${id}`, username: "", avatar: null });
const gif = (id: string) => ({ id, thumbUrl: "", fullUrl: "" });
const ctx = (over: Partial<MassCtx> = {}): MassCtx => ({ broadcastCount: 2, sensitive: false, ...over });
const form = (over: Partial<MassForm> = {}): MassForm => ({ ...initMassForm("acc1"), text: "hi", ...over });
const tpl = (over: Partial<PickedTemplate> = {}): PickedTemplate => ({
  source: "local", text: "t", displayText: "t", mediaCount: 0, price: 0, lockedText: false,
  isWelcome: false, media: [], previews: [], taggedUsers: [], ...over,
});
/** Every audience field, comparable. */
const audience = (s: MassForm) => ({
  includes: sorted(s.includes), excludes: sorted(s.excludes), smartInclude: sorted(s.smartInclude),
  smartExclude: sorted(s.smartExclude), seededFor: s.seededFor,
});
const ok = (accountId: string) => ({ accountId, ok: true });
const bad = (accountId: string) => ({ accountId, ok: false, error: "500" });
const DEFAULT_AUDIENCE = {
  includes: ["fans", "following"], excludes: [], smartInclude: [], smartExclude: [], seededFor: null,
};

describe("initMassForm", () => {
  it("a fresh compose defaults to fans + following, online-only on, the opener's account", () => {
    const f = initMassForm("acc1");
    expect(audience(f)).toEqual(DEFAULT_AUDIENCE);
    expect(f.onlineOnly).toBe(true);
    expect(f.accountId).toBe("acc1");
    expect(initMassForm().accountId).toBeNull();
  });
});

describe("massMessageReducer — audience", () => {
  it.each<[string, MassAction[], string[], string[]]>([
    ["include a list", [{ type: "toggleInclude", id: "L" }], ["L", "fans", "following"], []],
    ["exclude a list", [{ type: "toggleExclude", id: "L" }], ["fans", "following"], ["L"]],
    ["include then exclude moves it", [{ type: "toggleInclude", id: "L" }, { type: "toggleExclude", id: "L" }],
      ["fans", "following"], ["L"]],
    ["exclude then include moves it back", [{ type: "toggleExclude", id: "L" }, { type: "toggleInclude", id: "L" }],
      ["L", "fans", "following"], []],
    ["toggle twice is off", [{ type: "toggleExclude", id: "L" }, { type: "toggleExclude", id: "L" }],
      ["fans", "following"], []],
    ["system chip cycles include → off", [{ type: "cycleSystem", id: "fans" }], ["following"], []],
    ["system chip off → include", [{ type: "cycleSystem", id: "recent" }], ["fans", "following", "recent"], []],
  ])("%s (include/exclude never share an id)", (_n, actions, inc, exc) => {
    const s = run(form(), ...actions);
    expect(sorted(s.includes)).toEqual(inc);
    expect(sorted(s.excludes)).toEqual(exc);
    expect([...s.includes].filter((id) => s.excludes.has(id))).toEqual([]);
  });

  it.each<[string, MassAction[], number[], number[]]>([
    ["include a Smart List", [{ type: "toggleSmartInclude", id: 1 }], [1], []],
    ["exclude a Smart List", [{ type: "toggleSmartExclude", id: 1 }], [], [1]],
    ["include then exclude moves it", [{ type: "toggleSmartInclude", id: 1 }, { type: "toggleSmartExclude", id: 1 }], [], [1]],
    ["exclude then include moves it back", [{ type: "toggleSmartExclude", id: 1 }, { type: "toggleSmartInclude", id: 1 }], [1], []],
    ["toggle twice is off", [{ type: "toggleSmartInclude", id: 1 }, { type: "toggleSmartInclude", id: 1 }], [], []],
  ])("Smart Lists: %s (include/exclude never share an id)", (_n, actions, inc, exc) => {
    const s = run(form(), ...actions);
    expect([sorted(s.smartInclude), sorted(s.smartExclude)]).toEqual([inc, exc]);
  });

  // The audience has ONE owner and ONE reset: each of these is a single
  // reducer step that leaves every audience field at the default (lists,
  // Smart Lists, the MASSDMEXCLUDE seed). A second reset path — an effect, a
  // hook holding its own picks — has nothing left to reset: the composer reads
  // only the segment list from useSmartLists, and the step below did it all.
  const picked = (over: Partial<MassForm> = {}) => run(form(over),
    { type: "toggleInclude", id: "L" }, { type: "toggleExclude", id: "X" },
    { type: "toggleSmartInclude", id: 1 }, { type: "toggleSmartExclude", id: 2 },
    { type: "seedExclude", accountId: over.accountId ?? "acc1", listId: "M" });
  it.each<[string, () => MassForm, MassAction]>([
    ["account A → B", () => picked(), { type: "setAccount", id: "acc2" }],
    ["all-models on", () => picked(), { type: "setAllModels", on: true }],
    ["all-models off", () => ({ ...picked(), allModels: true, accountId: null }), { type: "setAllModels", on: false }],
  ])("%s resets the whole audience in that one step", (_n, before, action) => {
    const s = before();
    expect(audience(s)).not.toEqual(DEFAULT_AUDIENCE);
    expect(audience(massMessageReducer(s, action))).toEqual(DEFAULT_AUDIENCE);
  });

  // #19-1: setAccount delegates to audience/audienceReducer, whose first pick
  // (null → A) keeps what was clicked. Before, compose reset the audience (and
  // dropped media / previews / tags) on null → A too.
  it("CHANGED: the first pick (null → A) is no switch: the audience and media stay", () => {
    const s = run(form({ accountId: null, attached: [media(1)], previewCount: 1, taggedCreators: [tag(1)] }),
      { type: "toggleInclude", id: "L" }, { type: "toggleExclude", id: "X" }, { type: "toggleSmartInclude", id: 1 });
    const next = massMessageReducer(s, { type: "setAccount", id: "acc1" });
    expect(next.accountId).toBe("acc1");
    expect(audience(next)).toEqual(audience(s));
    expect(next).toMatchObject({ attached: [media(1)], previewCount: 1, taggedCreators: [tag(1)] });
  });

  it("all-models off → the picker's null → A seed: still the default audience, re-armed seed", () => {
    const s = run(picked(), { type: "setAllModels", on: true }, { type: "setAllModels", on: false },
      { type: "setAccount", id: "acc1" });
    expect(audience(s)).toEqual(DEFAULT_AUDIENCE);
    expect(run(s, { type: "seedExclude", accountId: "acc1", listId: "M" }).excludes).toEqual(new Set(["M"]));
  });

  it("re-asserting a scope is not a second reset (same reference back)", () => {
    const s = picked();
    expect(massMessageReducer(s, { type: "setAccount", id: "acc1" })).toBe(s);
    const on = run(s, { type: "setAllModels", on: true }, { type: "cycleSystem", id: "recent" });
    expect(massMessageReducer(on, { type: "setAllModels", on: true })).toBe(on);
    // All-models on dropped the account already: its implied null is no reset either.
    expect(massMessageReducer(on, { type: "setAccount", id: null })).toBe(on);
  });

  const scoped = { attached: [media(1)], previewCount: 1, taggedCreators: [tag(1)], price: "20", lockedText: true };
  it.each<[string, MassAction, Partial<MassForm>]>([
    ["account A → B drops A's media, previews and tags; keeps price and lock", { type: "setAccount", id: "acc2" },
      { accountId: "acc2", attached: [], previewCount: 0, taggedCreators: [], price: "20", lockedText: true }],
    ["all-models on drops those plus the account, price and lock", { type: "setAllModels", on: true },
      { allModels: true, accountId: null, attached: [], previewCount: 0, taggedCreators: [], price: "", lockedText: false }],
  ])("%s", (_n, action, want) => {
    expect(massMessageReducer(form(scoped), action)).toMatchObject(want);
  });

  it("MASSDMEXCLUDE seeds once per account; an untick sticks; an audience reset re-arms it", () => {
    let s = massMessageReducer(form(), { type: "seedExclude", accountId: "acc1", listId: "M" });
    expect([...s.excludes]).toEqual(["M"]);
    s = run(s, { type: "toggleExclude", id: "M" }, { type: "seedExclude", accountId: "acc1", listId: "M" });
    expect(s.excludes.size).toBe(0);
    // A → all-models → back to A: the reset re-arms the seed.
    s = run(s, { type: "setAllModels", on: true }, { type: "setAllModels", on: false },
      { type: "setAccount", id: "acc1" }, { type: "seedExclude", accountId: "acc1", listId: "M" });
    expect([...s.excludes]).toEqual(["M"]);
  });

  it.each<[string, Partial<MassForm>, string]>([
    ["all-models mode", { allModels: true, accountId: null }, "acc1"],
    ["a stale account", {}, "acc2"],
    ["an account already seeded", { seededFor: "acc1" }, "acc1"],
  ])("MASSDMEXCLUDE is not seeded in %s", (_n, over, aid) => {
    const s = form(over);
    expect(massMessageReducer(s, { type: "seedExclude", accountId: aid, listId: "M" })).toBe(s);
  });

  it("MASSDMEXCLUDE never lands on a list the operator included", () => {
    const s = run(form(), { type: "toggleInclude", id: "M" }, { type: "seedExclude", accountId: "acc1", listId: "M" });
    expect(s.includes.has("M")).toBe(true);
    expect(s.excludes.has("M")).toBe(false);
  });
});

describe("massMessageReducer — text, template, gifs, fan-out", () => {
  it("appendText appends to the text as it is now", () => {
    expect(run(form({ text: "a" }), { type: "appendText", v: "😀" }, { type: "appendText", v: "!" }).text).toBe("a😀!");
  });
  it("a non-GIF template clears picked GIFs; a GIF template seeds its GIF", () => {
    const s = form({ pickedGifs: [gif("old")] });
    expect(massMessageReducer(s, { type: "pickTemplate", t: tpl() }).pickedGifs).toEqual([]);
    expect(massMessageReducer(s, { type: "pickTemplate", t: tpl({ gifId: "g" }) }).pickedGifs.map((g) => g.id)).toEqual(["g"]);
  });
  it("addGif dedupes by id and closes the picker; removeGif drops one", () => {
    const s = run(form({ gifPickerOpen: true }), { type: "addGif", gif: gif("g") }, fieldAction("gifPickerOpen", true),
      { type: "addGif", gif: gif("g") });
    expect([s.pickedGifs.length, s.gifPickerOpen]).toEqual([1, false]);
    expect(massMessageReducer(s, { type: "removeGif", id: "g" }).pickedGifs).toEqual([]);
  });
  it("progress is {done,total}; results clear it and merge by account (a retry's round)", () => {
    let s = run(form(), { type: "progress", done: 0, total: 2 });
    expect(s.progress).toEqual({ done: 0, total: 2 });
    s = run(s, { type: "results", v: [ok("a"), bad("b")] }, { type: "results", v: [ok("b")] });
    expect([s.progress, s.results]).toEqual([null, [ok("a"), ok("b")]]);
  });
  it.each<[string, MassAction]>([
    ["all-models on", { type: "setAllModels", on: true }],
    ["all-models off", { type: "setAllModels", on: false }],
  ])("BUG: %s clears the fan-out results (were: shown after leaving all-models)", (_n, a) => {
    const s = form({ allModels: a.type === "setAllModels" && !a.on, accountId: null, results: [bad("a")] });
    expect(massMessageReducer(s, a).results).toBeNull();
  });
  it("gifSendsFailed spends the form: the failures are kept and validateMass refuses it", () => {
    const s = run(form({ pickedGifs: [gif("g1"), gif("g2")] }), { type: "progress", done: 0, total: 1 },
      { type: "gifSendsFailed", failed: [{ id: "g2", error: "boom" }] });
    expect([s.gifFailures, s.progress]).toEqual([[{ id: "g2", error: "boom" }], null]);
    expect(validateMass(s, ctx())).toBe(MASS_ALREADY_SENT);
  });
  // Same as the post (#13-1): once a model sent it, an edit would reach only
  // the failed models, so the content is locked until Start over.
  const partial = form({ allModels: true, accountId: null, results: [ok("a"), bad("b")] });
  it.each<[string, MassAction]>([
    ["text", fieldAction("text", "edited")],
    ["emoji", { type: "appendText", v: "!" }],
    ["schedule", fieldAction("schedule", "2030-01-01T10:00")],
    ["funnel", fieldAction("funnelId", 4)],
    ["online field", fieldAction("unreadLimit", "5")],
    ["system audience", { type: "cycleSystem", id: "fans" }],
    ["list include", { type: "toggleInclude", id: "L" }],
    ["GIF", { type: "addGif", gif: gif("g") }],
    ["template", { type: "pickTemplate", t: tpl({ text: "other" }) }],
    ["all-models off", { type: "setAllModels", on: false }],
  ])("BUG: a partial fan-out locks the content: %s is refused", (_n, a) => {
    expect(massMessageReducer(partial, a)).toBe(partial);
  });
  it.each<[string, MassAction[], Partial<MassForm>]>([
    ["the retry's lifecycle still runs", [{ type: "progress", done: 0, total: 1 }, { type: "results", v: [ok("b")] }],
      { results: [ok("a"), ok("b")], progress: null, text: "hi" }],
    ["Start over unlocks: results cleared, then an edit lands", [{ type: "discardResults" }, fieldAction("text", "edited")],
      { results: null, text: "edited" }],
  ])("%s", (_n, actions, want) => {
    expect(run(partial, ...actions)).toMatchObject(want);
  });
  // A round in flight (round 1: no results yet): its body is built, so an
  // edit would show content it doesn't send, and all-models off would land
  // its results in one-account mode.
  const inFlight = form({ allModels: true, accountId: null, progress: { done: 0, total: 2 } });
  it.each<[string, MassAction]>([
    ["text", fieldAction("text", "edited")],
    ["list include", { type: "toggleInclude", id: "L" }],
    ["template", { type: "pickTemplate", t: tpl({ text: "other" }) }],
    ["all-models off", { type: "setAllModels", on: false }],
  ])("BUG: a round in flight locks the content: %s is refused", (_n, a) => {
    expect(massMessageReducer(inFlight, a)).toBe(inFlight);
  });
  it("BUG: Start over is refused while a retry is in flight (its successes would be forgotten)", () => {
    const retrying = { ...partial, progress: { done: 0, total: 1 } };
    expect(massMessageReducer(retrying, { type: "discardResults" })).toBe(retrying);
    expect(run(retrying, { type: "discardResults" }, { type: "results", v: [ok("b")] }).results)
      .toEqual([ok("a"), ok("b")]);
  });
  it("every model failed: nothing went out, so no lock", () => {
    const s = form({ allModels: true, accountId: null, results: [bad("a")] });
    expect(massMessageReducer(s, fieldAction("text", "edited")).text).toBe("edited");
  });
  it("a field write of the same value is a no-op", () => {
    const s = form();
    expect(massMessageReducer(s, fieldAction("text", "hi"))).toBe(s);
  });
});

describe("validateMass — the one check (button and mutation)", () => {
  const smart = "Pick at least one audience list or Smart List to include";
  const lists = "Pick at least one audience list to include";
  it.each<[string, Partial<MassForm>, Partial<MassCtx>, string | null]>([
    ["a ready form", {}, {}, null],
    ["a spent form (broadcast landed, a GIF send failed) first", { gifFailures: [], text: "" }, { sensitive: true }, MASS_ALREADY_SENT],
    ["sensitive word first", { text: "" }, { sensitive: true }, SENSITIVE_BLOCK_MESSAGE],
    ["no account", { accountId: null }, {}, "Pick an account"],
    ["all-models with no model included", { allModels: true, accountId: null }, { broadcastCount: 0 }, "No models picked for broadcast"],
    ["BUG: the last failed model excluded after a round (was: No active models)",
      { allModels: true, accountId: null, results: [ok("a"), bad("b")] }, { broadcastCount: 0 },
      "Nothing to retry: every failed model is excluded"],
    ["all-models needs no account", { allModels: true, accountId: null }, {}, null],
    ["nothing to send", { text: "  " }, {}, "Add text, media, or a GIF"],
    ["media alone is enough", { text: "", attached: [media(1)] }, {}, null],
    ["a fresh-upload claim counts", { text: "", attached: [media(0, { _claim: { p: 1 } })] }, {}, null],
    ["BUG: all-models ignores media and says so (media can't be added there)", { allModels: true, accountId: null, text: "", attached: [media(1)] }, {}, "Add text or a GIF"],
    ["a GIF alone is enough", { text: "", pickedGifs: [gif("g")] }, {}, null],
    ["one account: extra GIFs go as their own sends", { pickedGifs: [gif("g1"), gif("g2")] }, {}, null],
    ["all-models: one GIF rides the broadcast", { allModels: true, accountId: null, pickedGifs: [gif("g1")] }, {}, null],
    ["BUG: all-models refuses a 2nd GIF (was: sent the first only, the rest dropped silently)",
      { allModels: true, accountId: null, pickedGifs: [gif("g1"), gif("g2")] }, {}, MASS_ONE_GIF_ALL_MODELS],
    ["no audience", { includes: new Set() }, {}, smart],
    ["an include Smart List is an audience", { includes: new Set(), smartInclude: new Set([1]) }, {}, null],
    ["…an exclude one is not", { includes: new Set(), smartExclude: new Set([1]) }, {}, smart],
    ["…not in all-models", { allModels: true, accountId: null, includes: new Set(), smartInclude: new Set([1]) }, {}, lists],
    ["price under the minimum", { price: "1" }, {}, PRICE_NOTE],
    ["all-models forces free (a typed price is moot)", { allModels: true, accountId: null, price: "1" }, {}, null],
    ["invalid price", { price: "abc" }, {}, "Invalid price"],
    ["invalid schedule", { schedule: "not a date" }, {}, "Invalid schedule date"],
  ])("%s", (_n, over, c, want) => {
    expect(validateMass(form(over), ctx(c))).toBe(want);
  });
});

describe("gifNote — the GIF strip's note", () => {
  it.each<[string, Partial<MassForm>, string]>([
    ["one GIF", { pickedGifs: [gif("g1")] }, "1 GIF attached"],
    ["one account: the rest go as their own sends", { pickedGifs: [gif("g1"), gif("g2")] },
      "2 GIFs — first rides this broadcast; rest fan out as standalone sends"],
    ["all-models: one GIF", { allModels: true, pickedGifs: [gif("g1")] }, "1 GIF attached"],
    ["all-models: a 2nd GIF says what validateMass says", { allModels: true, pickedGifs: [gif("g1"), gif("g2")] },
      MASS_ONE_GIF_ALL_MODELS],
  ])("%s", (_n, over, want) => {
    expect(gifNote(form(over))).toBe(want);
  });
});

describe("confirmPrompt", () => {
  it.each<[string, Partial<MassForm>, number, string]>([
    ["the audience groups", {}, 2, "Broadcast from 2 audience groups?"],
    ["one group", { includes: new Set(["fans"]) }, 2, "Broadcast from 1 audience group?"],
    ["a Smart List replaces the groups", { smartInclude: new Set([1]) }, 2, "Broadcast from 1 Smart List only?"],
    ["…an exclude one does not", { smartExclude: new Set([1]) }, 2, "Broadcast from 2 audience groups?"],
    ["all-models counts models", { allModels: true, accountId: null, smartInclude: new Set([1]) }, 3, "Broadcast from 3 models?"],
    ["one model", { allModels: true, accountId: null }, 1, "Broadcast from 1 model?"],
    ["a schedule", { schedule: "2030-01-01T10:00" }, 2, "Schedule from 2 audience groups?"],
  ])("%s", (_n, over, n, want) => {
    expect(confirmPrompt(form(over), n)).toBe(want);
  });
});

describe("buildMassBody — the one body", () => {
  it("a free text broadcast", () => {
    expect(buildMassBody(form({ text: " hi " }), false)).toEqual({
      text: "hi", scheduled_date: null, user_lists: ["fans", "following"], user_ids: [], excluded_users: [],
      excluded_user_lists: [], price: 0, locked_text: false, media_files: [],
    });
  });
  it.each<[string, Partial<MassForm>, Record<string, unknown>, string[]]>([
    ["paid with previews and lock", { price: "10", previewCount: 1, lockedText: true, attached: [media(5), media(6)] },
      { price: 10, locked_text: true, previews: [5], media_files: [5, 6] }, []],
    ["free drops previews and lock", { price: "", previewCount: 1, lockedText: true, attached: [media(5), media(6)] },
      { price: 0, locked_text: false, media_files: [5, 6] }, ["previews"]],
    ["a fresh upload rides as its claim", { attached: [media(0, { _claim: { p: 1 } }), media(7)] },
      { media_files: [{ p: 1 }, 7] }, []],
    ["all-models forces free and text-only, no tags",
      { allModels: true, accountId: null, price: "10", lockedText: true, previewCount: 1, attached: [media(5)],
        taggedCreators: [tag(9)] },
      { price: 0, locked_text: false, media_files: [] }, ["previews", "tagged_users"]],
    ["tags, funnel and the FIRST GIF ride along", { funnelId: 4, taggedCreators: [tag(9)], pickedGifs: [gif("g1"), gif("g2")] },
      { tagged_users: [9], funnel_id: 4, giphy_id: "g1" }, []],
    ["the schedule as ISO", { schedule: "2030-01-01T10:00" },
      { scheduled_date: new Date(2030, 0, 1, 10, 0).toISOString() }, []],
  ])("%s", (_n, over, want, absent) => {
    const body = buildMassBody(form(over), false);
    expect(body).toMatchObject(want);
    for (const k of absent) expect(body).not.toHaveProperty(k);
  });
  it.each<[string, Partial<PickedTemplate>, Record<string, unknown>]>([
    ["a FREE template after a PAID draft sends free and unlocked", {}, { price: 0, locked_text: false }],
    ["a PAID template sends its price and lock", { price: 25, lockedText: true }, { price: 25, locked_text: true }],
  ])("%s", (_n, t, want) => {
    const s = massMessageReducer(form({ price: "25", lockedText: true }), { type: "pickTemplate", t: tpl(t) });
    expect(buildMassBody(s, false)).toMatchObject(want);
  });
  it("a template picked in all-models mode never sends its tags", () => {
    const s = run(form(), { type: "setAllModels", on: true }, { type: "pickTemplate", t: tpl({ taggedUsers: [9] }) });
    expect(buildMassBody(s, false)).not.toHaveProperty("tagged_users");
  });
  it("an include segment replaces the list chips (OF unions lists and ids)", () => {
    const body = buildMassBody(form(), false, { userIds: [1, 2], excludeUserIds: [3] });
    expect(body).toMatchObject({ user_lists: [], user_ids: [1, 2], excluded_users: [3] });
  });
  it("online mode: only set, positive filters", () => {
    const f = form({ unreadLimit: "10.7", recentChatHours: "", excludeRepliedHours: "0", minTipped: "20", unsendAfterHours: "2" });
    const live = buildMassBody(f, true);
    expect(live).toMatchObject({ online_only: true, unread_limit: 10, min_tipped: 20, unsend_after_hours: 2 });
    expect(live).not.toHaveProperty("recent_chat_hours");
    expect(live).not.toHaveProperty("exclude_replied_hours");
    expect(buildMassBody(f, false)).not.toHaveProperty("online_only");
  });
});

describe("gifOnlyForm — a trailing GIF's own send", () => {
  const full = form({
    text: "paid text", price: "20", lockedText: true, attached: [media(5)], previewCount: 1, funnelId: 4,
    taggedCreators: [tag(9)], pickedGifs: [gif("g1"), gif("g2")], schedule: "2030-01-01T10:00",
    includes: new Set(["fans"]), excludes: new Set(["X"]), unreadLimit: "5",
  });
  it("carries only its GIF: no text, media, price, lock, previews, tags or funnel", () => {
    const body = buildMassBody(gifOnlyForm(full, gif("g2")), true, { userIds: [1], excludeUserIds: [2] });
    expect(body).toEqual({
      text: "", scheduled_date: new Date(2030, 0, 1, 10, 0).toISOString(), user_lists: [], user_ids: [1],
      excluded_users: [2], excluded_user_lists: ["X"], price: 0, locked_text: false, media_files: [],
      giphy_id: "g2", online_only: true, unread_limit: 5,
    });
  });
  it("…to the same audience as the main send", () => {
    const main = buildMassBody(full, true);
    const trailing = buildMassBody(gifOnlyForm(full, gif("g2")), true);
    for (const k of ["scheduled_date", "user_lists", "user_ids", "excluded_users", "excluded_user_lists", "online_only", "unread_limit"]) {
      expect(trailing[k]).toEqual(main[k]);
    }
  });
  it("is a valid form on its own", () => {
    expect(validateMass(gifOnlyForm(full, gif("g2")), ctx())).toBeNull();
  });
});
