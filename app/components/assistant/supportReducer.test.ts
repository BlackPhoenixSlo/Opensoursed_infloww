import { describe, expect, it } from "vitest";

import {
  appendDraft, buildPayload, canSend, droppedPhotos, errorText, initialSupportEntry, initialSupportState,
  MAX_SUPPORT_CHARS, MAX_SUPPORT_MESSAGES, MAX_SUPPORT_PHOTOS, mergeMessages, messagesOf, NO_SUPPORT, photoRoom,
  SUPPORT_FALLBACK_ERROR,
  supportEntryReducer, supportReducer, supportStatusOf, TOO_MANY_PHOTOS, type PendingPhoto, type SupportAction,
  type SupportEntry, type SupportEntryAction, type SupportMessage, type SupportState,
} from "./supportReducer";

const run = (actions: SupportAction[], from: SupportState = initialSupportState) => actions.reduce(supportReducer, from);
const msg = (id: number, from: "me" | "support" = "me", text = `m${id}`, photos: number[] = []): SupportMessage =>
  ({ id, from, text, at: "", photos: photos.map((p) => ({ id: p, w: 10, h: 10 })) });
const pic = (key: string): PendingPhoto => ({ key, blob: new Blob(["x"]), url: `blob:${key}` });
const ready = run([{ type: "loaded", messages: [msg(1)] }]);

describe("supportStatusOf", () => {
  it.each<[string, unknown, typeof NO_SUPPORT]>([
    ["not configured", { configured: false }, NO_SUPPORT],
    ["unrelated mock body", { count: 0, list: [] }, NO_SUPPORT],
    ["null", null, NO_SUPPORT],
    ["configured, none", { configured: true, unread: 0 }, { configured: true, unread: 0 }],
    ["configured, two", { configured: true, unread: 2 }, { configured: true, unread: 2 }],
    ["configured, junk count", { configured: true, unread: "3" }, { configured: true, unread: 0 }],
    ["configured, negative", { configured: true, unread: -1 }, { configured: true, unread: 0 }],
  ])("%s", (_n, body, want) => expect(supportStatusOf(body)).toEqual(want));
});

describe("messagesOf", () => {
  it("keeps well-formed rows and maps anything not support to me", () => {
    expect(messagesOf({ messages: [
      { id: 1, from: "me", text: "a", at: "t" }, { id: 2, from: "support", text: "b" },
      { id: 3, from: "evil", text: "c", at: "t" }, { id: "4", text: "d" }, null, { id: 5 },
      { id: 6, from: "support", text: "", photos: [{ id: 9, w: 4, h: 3 }, { id: "x" }, null, { id: 10 }] },
    ] })).toEqual([
      { id: 1, from: "me", text: "a", at: "t", photos: [] }, { id: 2, from: "support", text: "b", at: "", photos: [] },
      { id: 3, from: "me", text: "c", at: "t", photos: [] },
      { id: 6, from: "support", text: "", at: "", photos: [{ id: 9, w: 4, h: 3 }, { id: 10, w: 0, h: 0 }] },
    ]);
  });
  it.each([undefined, null, {}, { messages: "x" }])("no list → empty (%s)", (body) => expect(messagesOf(body)).toEqual([]));
});

describe("supportReducer", () => {
  it.each<[string, SupportAction[], Partial<SupportState>]>([
    ["first load failing shows the error", [{ type: "load_failed", error: "down" }], { phase: "failed", error: "down" }],
    ["retry after a failed load", [{ type: "load_failed", error: "down" }, { type: "load_started" }],
      { phase: "loading", error: null }],
    ["a successful poll recovers a failed load",
      [{ type: "load_failed", error: "down" }, { type: "polled", messages: [msg(1)] }],
      { phase: "ready", messages: [msg(1)], error: null }],
    ["a failed reload keeps the thread", [{ type: "loaded", messages: [msg(1)] }, { type: "load_failed", error: "down" }],
      { phase: "ready", messages: [msg(1)], error: "down" }],
    ["send takes the hub's thread",
      [{ type: "loaded", messages: [] }, { type: "send_started" },
        { type: "sent", messages: [msg(1), msg(2, "support")], keys: [] }],
      { sending: false, messages: [msg(1), msg(2, "support")] }],
    ["photo-only send clears the sent photos",
      [{ type: "loaded", messages: [] }, { type: "photos_added", photos: [pic("a")], requested: 1, converted: 0 }, { type: "send_started" },
        { type: "sent", messages: [msg(1, "me", "", [5])], keys: ["a"] }],
      { photos: [], sending: false, messages: [msg(1, "me", "", [5])] }],
    ["a photo added while sending stays pending",
      [{ type: "loaded", messages: [] }, { type: "photos_added", photos: [pic("a")], requested: 1, converted: 0 }, { type: "send_started" },
        { type: "photos_added", photos: [pic("b")], requested: 1, converted: 0 }, { type: "sent", messages: [msg(1)], keys: ["a"] }],
      { photos: [pic("b")] }],
    ["poll adds new messages and keeps photos",
      [{ type: "loaded", messages: [msg(1)] }, { type: "photos_added", photos: [pic("a")], requested: 1, converted: 0 },
        { type: "polled", messages: [msg(1), msg(2, "support")] }],
      { photos: [pic("a")], messages: [msg(1), msg(2, "support")] }],
    ["a stale poll never drops a message the send already showed",
      [{ type: "loaded", messages: [msg(1)] }, { type: "sent", messages: [msg(1), msg(2)], keys: [] },
        { type: "polled", messages: [msg(1)] }],
      { messages: [msg(1), msg(2)] }],
    ["more than four photos are cut with a note",
      [{ type: "photos_added", photos: [pic("a"), pic("b"), pic("c")], requested: 3, converted: 0 },
        { type: "photos_added", photos: [pic("d"), pic("e")], requested: 2, converted: 0 }],
      { photos: [pic("a"), pic("b"), pic("c"), pic("d")], error: TOO_MANY_PHOTOS }],
    ["files skipped before decoding still get the note",
      [{ type: "photos_added", photos: [pic("a"), pic("b"), pic("c")], requested: 3, converted: 0 },
        { type: "photos_added", photos: [pic("d")], requested: 3, converted: 0 }],
      { photos: [pic("a"), pic("b"), pic("c"), pic("d")], error: TOO_MANY_PHOTOS }],
    ["picking when full only shows the note",
      [{ type: "photos_added", photos: [pic("a"), pic("b"), pic("c"), pic("d")], requested: 4, converted: 0 },
        { type: "photos_added", photos: [], requested: 1, converted: 0 }],
      { photos: [pic("a"), pic("b"), pic("c"), pic("d")], error: TOO_MANY_PHOTOS }],
    ["remove one photo",
      [{ type: "photos_added", photos: [pic("a"), pic("b")], requested: 2, converted: 0 }, { type: "photo_removed", key: "a" }],
      { photos: [pic("b")] }],
    ["a photo that cannot be read shows why",
      [{ type: "loaded", messages: [] }, { type: "photo_failed", converted: 0, error: "That file isn't a photo." }],
      { error: "That file isn't a photo.", phase: "ready" }],
    ["conversion success releases only its own reservation",
      [{ type: "photos_converting", count: 3 }, { type: "photos_converting", count: 1 },
        { type: "photos_added", photos: [pic("a"), pic("b"), pic("c")], requested: 3, converted: 3 }],
      { photos: [pic("a"), pic("b"), pic("c")], converting: 1, error: null }],
    ["conversion failure releases its reservation without going negative",
      [{ type: "photos_converting", count: 1 }, { type: "photo_failed", error: "bad photo", converted: 2 }],
      { converting: 0, error: "bad photo" }],
    ["a failed send shows why and retains the pending photo",
      [{ type: "loaded", messages: [] }, { type: "photos_added", photos: [pic("a")], requested: 1, converted: 0 },
        { type: "send_started" }, { type: "send_failed", error: "e" }],
      { sending: false, error: "e", photos: [pic("a")] }],
  ])("%s", (_n, actions, want) => expect(run(actions)).toMatchObject(want));

  it("send_started is a no-op while loading or already sending", () => {
    expect(supportReducer(initialSupportState, { type: "send_started" })).toBe(initialSupportState);
    const busy = { ...ready, sending: true };
    expect(supportReducer(busy, { type: "send_started" })).toBe(busy);
  });

  it("load_started while already loaded changes nothing", () => {
    expect(supportReducer(ready, { type: "load_started" })).toBe(ready);
  });

  it("a poll with nothing new returns the same state", () => {
    expect(supportReducer(ready, { type: "polled", messages: [msg(1)] })).toBe(ready);
  });
});

describe("mergeMessages", () => {
  const a = msg(1);
  const b = msg(2, "support");
  it.each<[string, SupportMessage[], SupportMessage[], SupportMessage[]]>([
    ["append", [a], [a, b], [a, b]],
    ["out of order from the hub", [a], [b, a], [a, b]],
    ["edited text replaces", [a], [msg(1, "me", "changed")], [msg(1, "me", "changed")]],
    ["photos arriving replace", [a], [msg(1, "me", "m1", [3])], [msg(1, "me", "m1", [3])]],
    ["an older snapshot keeps newer messages", [a, b, msg(3)], [a], [a, b, msg(3)]],
  ])("%s", (_n, cur, next, want) => expect(mergeMessages(cur, next)).toEqual(want));

  it("keeps the old objects when unchanged", () => {
    const cur = [a, b];
    expect(mergeMessages(cur, [msg(1), msg(2, "support")])).toBe(cur);
    expect(mergeMessages(cur, [msg(1), msg(2, "support"), msg(3)])[0]).toBe(a);
  });

  it("keeps only the newest messages", () => {
    const many = Array.from({ length: MAX_SUPPORT_MESSAGES }, (_, i) => msg(i + 1));
    const out = mergeMessages(many, [msg(MAX_SUPPORT_MESSAGES + 1)]);
    expect(out).toHaveLength(MAX_SUPPORT_MESSAGES);
    expect([out[0].id, out[out.length - 1].id]).toEqual([2, MAX_SUPPORT_MESSAGES + 1]);
  });
});

describe("appendDraft / supportEntryReducer", () => {
  it.each<[string, string, string, string]>([
    ["empty draft takes the question", "", "  how do I tag fans? ", "how do I tag fans?"],
    ["blank draft is replaced", "  \n ", "q", "q"],
    ["a draft is kept and the question goes on a new line", "mine  ", "q", "mine\nq"],
    ["nothing to add", "mine", "   ", "mine"],
  ])("%s", (_n, draft, add, want) => expect(appendDraft(draft, add)).toBe(want));

  it("is capped at the hub's limit", () => {
    expect(appendDraft("a".repeat(MAX_SUPPORT_CHARS), "more")).toHaveLength(MAX_SUPPORT_CHARS);
  });

  const go = (actions: SupportEntryAction[], from: SupportEntry = initialSupportEntry) =>
    actions.reduce(supportEntryReducer, from);
  it.each<[string, SupportEntryAction[], SupportEntry]>([
    ["open and close keep the draft", [{ type: "draft", text: "half" }, { type: "open" }, { type: "close" }],
      { open: false, draft: "half" }],
    ["contact opens with the question", [{ type: "contact", question: "Why no reply?" }],
      { open: true, draft: "Why no reply?" }],
    ["contact never overwrites a draft", [{ type: "draft", text: "half" }, { type: "contact", question: "Why?" }],
      { open: true, draft: "half\nWhy?" }],
    ["send clears the draft", [{ type: "open" }, { type: "draft", text: " x " }, { type: "sent", text: "x" }],
      { open: true, draft: "" }],
    ["text typed while sending survives the reply",
      [{ type: "draft", text: "x" }, { type: "draft", text: "x and more" }, { type: "sent", text: "x" }],
      { open: false, draft: "x and more" }],
  ])("%s", (_n, actions, want) => expect(go(actions)).toEqual(want));

  it("draft is capped at the hub's limit", () => {
    expect(go([{ type: "draft", text: "a".repeat(MAX_SUPPORT_CHARS + 50) }]).draft).toHaveLength(MAX_SUPPORT_CHARS);
  });

  it("same draft or repeated open returns the same state", () => {
    const s = go([{ type: "open" }, { type: "draft", text: "x" }]);
    expect(supportEntryReducer(s, { type: "draft", text: "x" })).toBe(s);
    expect(supportEntryReducer(s, { type: "open" })).toBe(s);
  });
});

describe("canSend / buildPayload / photoRoom", () => {
  it.each<[string, SupportState, string, boolean]>([
    ["still loading", initialSupportState, "x", false],
    ["blank", ready, "   ", false],
    ["in flight", { ...ready, sending: true }, "x", false],
    ["converting", run([{ type: "photos_converting", count: 1 }], ready), "x", false],
    ["ready", ready, "x", true],
    ["photo only", { ...ready, photos: [pic("a")] }, "", true],
    ["photo only, in flight", { ...ready, photos: [pic("a")], sending: true }, "", false],
    ["after a failed load", { ...initialSupportState, phase: "failed" }, "x", true],
  ])("%s", (_n, s, draft, want) => expect(canSend(s, draft)).toBe(want));

  it("payload is the trimmed text and the pending photos", () => {
    expect(buildPayload(ready, "  need bulk tags \n")).toEqual({ text: "need bulk tags", photos: [] });
    expect(buildPayload({ ...ready, photos: [pic("a")] }, "")).toEqual({ text: "", photos: [pic("a")] });
  });

  it("photoRoom counts down to zero", () => {
    expect(photoRoom(ready)).toBe(MAX_SUPPORT_PHOTOS);
    expect(photoRoom({ ...ready, photos: [pic("a"), pic("b"), pic("c"), pic("d")] })).toBe(0);
  });

  it("droppedPhotos lists the previews to release", () => {
    expect(droppedPhotos([pic("a"), pic("b")], [pic("b")]).map((p) => p.key)).toEqual(["a"]);
    expect(MAX_SUPPORT_PHOTOS).toBe(4);
  });
});

describe("errorText", () => {
  it.each<[string, unknown, string]>([
    ["relay detail string", { body: { detail: "Support is unreachable right now — try again soon." } },
      "Support is unreachable right now — try again soon."],
    ["object detail", { body: { detail: { error: "x" } } }, SUPPORT_FALLBACK_ERROR],
    ["plain error", new Error("boom"), SUPPORT_FALLBACK_ERROR],
    ["null", null, SUPPORT_FALLBACK_ERROR],
  ])("%s", (_n, e, want) => expect(errorText(e)).toBe(want));
});
