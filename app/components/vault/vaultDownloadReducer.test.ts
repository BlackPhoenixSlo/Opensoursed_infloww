import { describe, expect, it } from "vitest";

import { type VaultMedia } from "@/lib/relay";

import {
  CANCELLED, MAX_DIRECT_STRIKES, UNFILED, canRetry, fileName, folderOf, initialDownloadState, isBusy, safeName,
  sourceFor, summarize, toItems, vaultDownloadReducer, type Action, type DlState,
} from "./vaultDownloadReducer";

const run = (actions: Action[], from: DlState = initialDownloadState): DlState => actions.reduce(vaultDownloadReducer, from);

const media = (id: number, type = "photo", url: string | null = `https://cdn2.onlyfans.com/files/a/${id}.jpg?Policy=x`,
  listStates: unknown[] = []) =>
  ({ id, type, files: url ? { full: { url } } : { full: { url: null } }, listStates }) as unknown as VaultMedia;

const start: Action = { type: "start", mode: "selection", label: "3 selected", creator: "amy", directAllowed: true };
const listed = (ids: number[]): Action => ({ type: "listed", items: toItems(ids.map((i) => media(i)), null) });
const running = run([start, listed([1, 2, 3])]);
const statuses = (s: DlState) => s.items.map((i) => `${i.id}:${i.status}`);

describe("phases", () => {
  it.each<[string, Action[], DlState["phase"]]>([
    ["start lists", [start], "listing"],
    ["listed runs", [start, listed([1])], "running"],
    ["an empty listing is done at once", [start, listed([])], "done"],
    ["listFailed ends the run", [start, { type: "listFailed", error: "boom" }], "done"],
    ["the last item settling ends the run", [start, listed([1]), { type: "itemStart", id: 1 },
      { type: "itemDone", id: 1, source: "direct", bytes: 5 }], "done"],
    ["a failure also settles", [start, listed([1]), { type: "itemStart", id: 1 },
      { type: "itemFailed", id: 1, error: "x" }], "done"],
    ["cancel while listing", [start, { type: "cancel" }], "cancelled"],
    ["cancel while running", [start, listed([1, 2]), { type: "cancel" }], "cancelled"],
  ])("%s", (_n, actions, phase) => {
    expect(run(actions).phase).toBe(phase);
  });

  it("one run at a time: start while busy is ignored", () => {
    expect(vaultDownloadReducer(running, { ...start, label: "other" })).toBe(running);
  });
  it("close only when idle-able; resets", () => {
    expect(vaultDownloadReducer(running, { type: "close" })).toBe(running);
    const done = run([{ type: "cancel" }], running);
    expect(vaultDownloadReducer(done, { type: "close" })).toEqual(initialDownloadState);
  });
  it("listFailed records why", () => {
    expect(run([start, { type: "listFailed", error: "relay 500" }]).error).toBe("relay 500");
  });
  it("isBusy", () => {
    expect([initialDownloadState, run([start]), running, run([{ type: "cancel" }], running)].map(isBusy))
      .toEqual([false, true, true, false]);
  });
});

describe("items", () => {
  it("listed drops duplicate ids (a media in two pages)", () => {
    expect(run([start, listed([1, 2, 1])]).items.map((i) => i.id)).toEqual([1, 2]);
  });
  it("start -> progress -> done records source and bytes", () => {
    const s = run([{ type: "itemStart", id: 2 }, { type: "itemProgress", id: 2, bytes: 10 }], running);
    expect(s.items[1]).toMatchObject({ status: "active", bytes: 10 });
    const d = run([{ type: "itemDone", id: 2, source: "relay", bytes: 99 }], s);
    expect(d.items[1]).toMatchObject({ status: "done", source: "relay", bytes: 99, error: null });
  });
  it.each<[string, Action]>([
    ["progress on a queued item", { type: "itemProgress", id: 1, bytes: 7 }],
    ["done on a queued item", { type: "itemDone", id: 1, source: "direct", bytes: 7 }],
  ])("%s is ignored", (_n, a) => {
    expect(run([a], running).items[0]).toMatchObject({ status: "queued", bytes: 0 });
  });
  it("cancel fails what is queued or active, keeps what is done", () => {
    const s = run([{ type: "itemStart", id: 1 }, { type: "itemDone", id: 1, source: "direct", bytes: 3 },
      { type: "itemStart", id: 2 }, { type: "cancel" }], running);
    expect(statuses(s)).toEqual(["1:done", "2:failed", "3:failed"]);
    expect(s.items[2].error).toBe(CANCELLED);
  });
  it("a late itemFailed after cancel does not overwrite", () => {
    const s = run([{ type: "itemStart", id: 1 }, { type: "cancel" }, { type: "itemFailed", id: 1, error: "abort" }], running);
    expect(s.items[0].error).toBe(CANCELLED);
  });
  it("retryFailed requeues only the failed ones", () => {
    const s = run([{ type: "itemStart", id: 1 }, { type: "itemDone", id: 1, source: "direct", bytes: 3 },
      { type: "itemStart", id: 2 }, { type: "itemFailed", id: 2, error: "relay 502" },
      { type: "itemStart", id: 3 }, { type: "itemFailed", id: 3, error: "x" }], running);
    expect(s.phase).toBe("done");
    expect(canRetry(s)).toBe(true);
    const r = run([{ type: "retryFailed" }], s);
    expect(r.phase).toBe("running");
    expect(statuses(r)).toEqual(["1:done", "2:queued", "3:queued"]);
  });
  it("retryFailed with nothing failed is a no-op", () => {
    const s = run([1, 2, 3].flatMap((id): Action[] => [{ type: "itemStart", id },
      { type: "itemDone", id, source: "direct", bytes: 1 }]), running);
    expect(vaultDownloadReducer(s, { type: "retryFailed" })).toBe(s);
  });
  it("summarize counts sources", () => {
    const s = run([{ type: "itemStart", id: 1 }, { type: "itemDone", id: 1, source: "direct", bytes: 3 },
      { type: "itemStart", id: 2 }, { type: "itemDone", id: 2, source: "relay", bytes: 4 },
      { type: "itemStart", id: 3 }], running);
    expect(summarize(s)).toEqual({ total: 3, done: 2, failed: 0, active: 1, bytes: 7, direct: 1, relay: 1 });
  });
});

describe("source", () => {
  it.each<[string, boolean, number, string]>([
    ["no proxy, no strikes", true, 0, "direct"],
    ["no proxy, below the limit", true, MAX_DIRECT_STRIKES - 1, "direct"],
    ["no proxy, at the limit", true, MAX_DIRECT_STRIKES, "relay"],
    ["proxied account", false, 0, "relay"],
  ])("%s -> %s", (_n, directAllowed, directStrikes, want) => {
    expect(sourceFor({ directAllowed, directStrikes })).toBe(want);
  });
  it("strikes accumulate and a new run resets them", () => {
    const s = run([{ type: "directStrike" }, { type: "directStrike" }], running);
    expect(sourceFor(s)).toBe("relay");
    const again = run([{ type: "cancel" }, start], s);
    expect(again.directStrikes).toBe(0);
  });
});

describe("paths", () => {
  it.each<[number, string | null, string, string]>([
    [1, "https://cdn2.onlyfans.com/files/a/b/1080x1350_abc.jpg?Policy=x", "photo", "1.jpg"],
    [2, "https://cdn2.onlyfans.com/files/a/b/src.MP4?Expires=1", "video", "2.mp4"],
    [3, "https://cdn2.onlyfans.com/files/noext?x", "video", "3.mp4"],
    [4, null, "audio", "4.mp3"],
    [5, null, "weird", "5.bin"],
    [6, "not a url", "photo", "6.jpg"],
  ])("fileName(%s, %s, %s) = %s", (id, url, kind, want) => {
    expect(fileName(id, url, kind)).toBe(want);
  });
  it.each<[string, string]>([
    ["Beach / 2024", "Beach _ 2024"],
    ["..", "_"],
    ["a:b*c?d", "a_b_c_d"],
    ["  ok. ", "ok"],
    ["x".repeat(100), "x".repeat(80)],
  ])("safeName(%j) = %j", (s, want) => {
    expect(safeName(s)).toBe(want);
  });
  it.each<[string, unknown[], string | null, string]>([
    ["forced folder wins", [{ type: "custom", name: "A", hasMedia: true }], "Chosen/x", "Chosen_x"],
    ["first custom folder", [{ type: "messages", name: "Messages" }, { type: "custom", name: "Beach" }], null, "Beach"],
    ["no custom folder", [{ type: "posts", name: "Posts" }], null, UNFILED],
    ["none", [], null, UNFILED],
  ])("folderOf: %s", (_n, ls, forced, want) => {
    expect(folderOf(media(1, "photo", null, ls), forced)).toBe(want);
  });
  it("toItems: DRM-only video has no url, mp4 name", () => {
    const [it0] = toItems([media(9, "video", null)], null);
    expect(it0).toMatchObject({ id: 9, url: null, name: "9.mp4", status: "queued", folder: UNFILED });
  });
});
