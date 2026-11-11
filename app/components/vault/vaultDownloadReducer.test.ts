import { describe, expect, it } from "vitest";

import { type VaultMedia } from "@/lib/relay";

import {
  BUSY_OFF, CANCELLED, DOWNLOAD_OFF, FINISHED_MAX, MAX_DIRECT_STRIKES, RESTRICTED_OFF, SHARE_BATCH_BYTES,
  SHARE_COUNT_OFF, SHARE_HELD_BYTES, SHARE_MODE_OFF, UNFILED, UNSAVED_OFF, addToBatches,
  batchLabel, busyOff, canFetchMore, canQueue, canRetry, dlAccess, downloadGate, fileName, folderOf, countText,
  heldBytes, holdsFiles, initialDownloadState, isBusy, mimeFor, outcomeParts, panelTitle, progressText, queues,
  readyBatch, retryable, retryJobOf, safeName, sourceFor, summarize, toItems, unsaved,
  vaultDownloadReducer, type Action, type DlAccess, type DlBatch, type DlJobArgs, type DlMode, type DlSink,
  type DlState,
} from "./vaultDownloadReducer";

const run = (actions: Action[], from: DlState = initialDownloadState): DlState => actions.reduce(vaultDownloadReducer, from);

const media = (id: number, type = "photo", url: string | null = `https://cdn2.onlyfans.com/files/a/${id}.jpg?Policy=x`,
  listStates: unknown[] = []) =>
  ({ id, type, files: url ? { full: { url } } : { full: { url: null } }, listStates }) as unknown as VaultMedia;

const start: Action = { type: "start", mode: "selection", label: "3 selected", accountId: "acc-amy", creator: "amy" };
const direct: Action = { type: "direct", allowed: true, attempt: 1 };
const listed = (ids: number[], attempt = 1): Action => ({ type: "listed", items: toItems(ids.map((i) => media(i)), null), attempt });
const running = run([start, direct, listed([1, 2, 3])]);
const statuses = (s: DlState) => s.items.map((i) => `${i.id}:${i.status}`);

describe("phases", () => {
  it.each<[string, Action[], DlState["phase"]]>([
    ["start lists", [start], "listing"],
    ["listed runs", [start, listed([1])], "running"],
    ["an empty listing is done at once", [start, listed([])], "done"],
    ["a listing error ends the run", [start, { type: "runError", error: "boom", attempt: 1 }], "done"],
    ["the last item settling ends the run", [start, listed([1]), { type: "itemStart", attempt: 1, id: 1 },
      { type: "itemDone", attempt: 1, id: 1, source: "direct", bytes: 5 }], "done"],
    ["a failure also settles", [start, listed([1]), { type: "itemStart", attempt: 1, id: 1 },
      { type: "itemFailed", attempt: 1, id: 1, error: "x" }], "done"],
    ["cancel while listing", [start, { type: "cancel" }], "cancelled"],
    ["cancel while running", [start, listed([1, 2]), { type: "cancel" }], "cancelled"],
  ])("%s", (_n, actions, phase) => {
    expect(run(actions).phase).toBe(phase);
  });

  it("one run at a time: start while busy is ignored", () => {
    expect(vaultDownloadReducer(running, { ...start, label: "other" })).toBe(running);
  });
  it("the run keeps its own model: a start for another refused while busy, retry still the first's", () => {
    const failed = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "itemFailed", attempt: 1, id: 1, error: "relay 502" },
      ...[2, 3].flatMap((id): Action[] => [{ type: "itemStart", attempt: 1, id },
        { type: "itemDone", attempt: 1, id, source: "direct", bytes: 1 }])],
    running);
    expect(failed).toMatchObject({ phase: "done", accountId: "acc-amy", creator: "amy" });
    const other: Action = { ...start, accountId: "acc-bea", creator: "bea" };
    expect(vaultDownloadReducer(running, other)).toBe(running);
    const retried = vaultDownloadReducer(failed, { type: "retryFailed" });
    expect(retried).toMatchObject({ phase: "running", accountId: "acc-amy", creator: "amy" });
    expect(run([other])).toMatchObject({ phase: "listing", accountId: "acc-bea", creator: "bea" });
  });
  it("close only when idle-able; resets", () => {
    expect(vaultDownloadReducer(running, { type: "close" })).toBe(running);
    const done = run([{ type: "cancel" }], running);
    expect(vaultDownloadReducer(done, { type: "close" })).toEqual({ ...initialDownloadState, attempt: 1, seq: 1 });
  });
  it("a listing error records why on the one failure channel", () => {
    expect(run([start, { type: "runError", error: "relay 500", attempt: 1 }]).runError).toBe("relay 500");
  });
  // #28/#34: run-level actions carry their attempt; an older run's late result never lands on the new one.
  it.each<[string, Action[], DlState["phase"], number]>([
    ["listed of an older attempt", [start, { type: "cancel" }, start, listed([1, 2], 1)], "listing", 0],
    ["listed of this attempt", [start, { type: "cancel" }, start, listed([1, 2], 2)], "running", 2],
  ])("%s", (_n, actions, phase, n) => {
    const s = run(actions);
    expect([s.phase, s.items.length]).toEqual([phase, n]);
  });
  it.each<[string, Action[], boolean]>([
    ["direct while listing", [start, direct], true],
    ["direct of an older attempt", [start, { ...direct, attempt: 0 } as Action], false],
    ["direct after listing", [start, listed([1]), direct], false],
    ["start resets it", [start, direct, { type: "cancel" }, start], false],
  ])("%s", (_n, actions, want) => {
    expect(run(actions).directAllowed).toBe(want);
  });
  it("isBusy: listing or running (an open picker holds the slot through holdsFiles, not isBusy)", () => {
    expect([initialDownloadState, run([{ type: "pick" }]), run([start]), running, run([{ type: "cancel" }], running)]
      .map(isBusy)).toEqual([false, false, true, true, false]);
  });
});

describe("picker, notes and run errors (#11, #17, #21: no useStates beside the reducer)", () => {
  it.each<[string, Action[], DlState["phase"], boolean, string, string, DlState?]>([
    ["pick opens the picker", [{ type: "pick" }], "idle", true, "", ""],
    ["the picker closed: back to idle", [{ type: "pick" }, { type: "pickClosed" }], "idle", false, "", ""],
    ["a folder picked: the run lists", [{ type: "pick" }, start], "listing", false, "", ""],
    ["the picker threw: idle with why, as a note", [{ type: "pick" }, { type: "pickClosed", error: "SecurityError" }],
      "idle", false, "", "Folder picker: SecurityError"],
    ["pickClosed outside picking is a no-op", [start, { type: "pickClosed" }], "listing", false, "", ""],
    ["a new pick clears an old note", [{ type: "pick" }, { type: "pickClosed", error: "x" }, { type: "pick" }],
      "idle", true, "", ""],
    ["runError outside a run changes nothing", [{ type: "runError", error: "x", attempt: 0 }], "idle", false, "", ""],
    ["runError of an older attempt changes nothing", [start, { type: "runError", error: "x", attempt: 0 }],
      "listing", false, "", ""],
    ["runError while listing ends the run", [start, { type: "runError", error: "x", attempt: 1 }], "done", false, "x", ""],
    // #40: a start refused (a run holds the slot) still closes its picker; the run below goes on.
    ["a refused start ends its picker", [start], "listing", false, "", "", { ...run([start]), picking: true }],
  ])("%s", (_n, actions, phase, picking, runError, note, base) => {
    const s = run(actions, base);
    expect([s.phase, s.picking, s.runError, s.note]).toEqual([phase, picking, runError, note]);
  });
  // #428: the page's one download outlives a Creator switch; a picker another model opened and closed leaves the
  // finished run below as it was (its card, its account, its Retry), and no Retry runs while that picker is open.
  it("a picker opened over a finished run: Retry off while open; closed, the run and its Retry are back", () => {
    const failed = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "itemFailed", attempt: 1, id: 1, error: "x" }],
      run([start, direct, listed([1])]));
    expect(canRetry(failed)).toBe(true);
    const open = vaultDownloadReducer(failed, { type: "pick" });
    expect([open.picking, canRetry(open), vaultDownloadReducer(open, { type: "retryFailed" }) === open]).toEqual([true, false, true]);
    expect(vaultDownloadReducer(open, { type: "close" })).toBe(open);
    const back = vaultDownloadReducer(open, { type: "pickClosed" });
    expect(back).toEqual(failed);
    expect(canRetry(back)).toBe(true);
  });
  it("the run itself threw: nothing stays active, the failed ones can be retried", () => {
    const s = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "runError", error: "boom", attempt: 1 }], running);
    expect(s.phase).toBe("done");
    expect(statuses(s)).toEqual(["1:failed", "2:failed", "3:failed"]);
    expect(canRetry(s)).toBe(true);
  });
  // #445: where a folder run saves rides its `start`; the next run / a close drops it, a picker over it keeps it.
  it.each<[string, Action[], string[] | null]>([
    ["its start sets it", [], ["amy"]],
    ["a picker over the run keeps it", [{ type: "pick" }], ["amy"]],
    ["a share run has none", [{ type: "close" }, { ...start, sink: "share" }], null],
  ])("savedAt: %s", (_n, after, dirs) => {
    const at = { root: {} as FileSystemDirectoryHandle, dirs: ["amy"] };
    const s = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "itemDone", attempt: 1, id: 1, source: "direct", bytes: 1 },
                   ...after], run([{ ...start, savedAt: at }, direct, listed([1])]));
    expect(s.savedAt?.dirs ?? null).toEqual(dirs);
  });
  it("runError after a Cancel changes nothing", () => {
    const cancelled = run([{ type: "cancel" }], running);
    expect(vaultDownloadReducer(cancelled, { type: "runError", error: "boom", attempt: 1 })).toBe(cancelled);
  });
  // #17: a share sheet failing mid-run is a note; the run, its items and its batches go on.
  it("a share-sheet note while running keeps running and keeps the items", () => {
    const mid = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "itemDone", attempt: 1, id: 1, source: "direct",
      bytes: 1 }, { type: "itemStart", attempt: 1, id: 2 }], running);
    const s = vaultDownloadReducer(mid, { type: "note", text: "NotAllowedError" });
    expect({ ...s, note: "" }).toEqual(mid);
    expect([s.phase, s.note, statuses(s)]).toEqual(["running", "NotAllowedError", ["1:done", "2:active", "3:queued"]]);
  });
  it.each<[string, Action]>([
    ["a saved batch", { type: "batchSaved", index: 0, attempt: 1 }],
    ["the links shared", { type: "links", ok: true, attempt: 1 }],
  ])("%s clears the note", (_n, a) => {
    const shareDone = run([{ ...start, sink: "share" }, listed([1]), { type: "itemStart", attempt: 1, id: 1 },
      { type: "itemDone", attempt: 1, id: 1, source: "direct", bytes: 1 }, { type: "note", text: "x" }]);
    expect(vaultDownloadReducer(shareDone, a).note).toBe("");
  });
  it("Retry failed clears the note and the run error", () => {
    const threw = run([{ type: "runError", error: "boom", attempt: 1 }, { type: "note", text: "x" }], running);
    const s = vaultDownloadReducer(threw, { type: "retryFailed" });
    expect([s.runError, s.note, s.phase]).toEqual(["", "", "running"]);
  });
  it("pick is refused while a run holds files", () => {
    expect(vaultDownloadReducer(running, { type: "pick" })).toBe(running);
  });
});

describe("attempts (#5: a cancelled worker can't touch the retry)", () => {
  const failedAll = run([1, 2, 3].flatMap((id): Action[] => [{ type: "itemStart", attempt: 1, id }]).concat(
    [{ type: "cancel" }]), running);
  const retried = run([{ type: "retryFailed" }], failedAll);
  it("start and retry bump the attempt; a new run never reuses one", () => {
    expect([running.attempt, retried.attempt]).toEqual([1, 2]);
    expect(run([{ type: "close" }, start], failedAll).attempt).toBe(2);
  });
  it.each<[string, Action, string]>([
    ["old attempt's late itemFailed(cancelled) on a requeued item", { type: "itemFailed", attempt: 1, id: 1, error: CANCELLED }, "1:queued"],
    ["old attempt's itemStart", { type: "itemStart", attempt: 1, id: 1 }, "1:queued"],
    ["old attempt's itemDone", { type: "itemDone", attempt: 1, id: 1, source: "relay", bytes: 9 }, "1:queued"],
    ["itemFailed on a queued item (never started)", { type: "itemFailed", attempt: 2, id: 1, error: "x" }, "1:queued"],
    ["the current attempt's itemStart", { type: "itemStart", attempt: 2, id: 1 }, "1:active"],
  ])("%s", (_n, a, want) => {
    expect(statuses(run([a], retried))[0]).toBe(want);
  });
  it("old attempt's itemFailed after the new worker started it: the new attempt keeps it", () => {
    const s = run([{ type: "itemStart", attempt: 2, id: 1 }, { type: "itemFailed", attempt: 1, id: 1, error: CANCELLED },
      { type: "itemDone", attempt: 2, id: 1, source: "relay", bytes: 4 }], retried);
    expect(s.items[0]).toMatchObject({ status: "done", bytes: 4, error: null });
  });
  it("old attempt's directStrike is ignored", () => {
    expect(run([{ type: "directStrike", attempt: 1 }], retried).directStrikes).toBe(0);
  });
});

describe("items", () => {
  it("listed drops duplicate ids (a media in two pages)", () => {
    expect(run([start, listed([1, 2, 1])]).items.map((i) => i.id)).toEqual([1, 2]);
  });
  it("start -> progress -> done records source and bytes", () => {
    const s = run([{ type: "itemStart", attempt: 1, id: 2 }, { type: "itemProgress", attempt: 1, id: 2, bytes: 10 }], running);
    expect(s.items[1]).toMatchObject({ status: "active", bytes: 10 });
    const d = run([{ type: "itemDone", attempt: 1, id: 2, source: "relay", bytes: 99 }], s);
    expect(d.items[1]).toMatchObject({ status: "done", source: "relay", bytes: 99, error: null });
  });
  it.each<[string, Action]>([
    ["progress on a queued item", { type: "itemProgress", attempt: 1, id: 1, bytes: 7 }],
    ["done on a queued item", { type: "itemDone", attempt: 1, id: 1, source: "direct", bytes: 7 }],
  ])("%s is ignored", (_n, a) => {
    expect(run([a], running).items[0]).toMatchObject({ status: "queued", bytes: 0 });
  });
  it("cancel marks what is queued or active cancelled (not failed), keeps what is done", () => {
    const s = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "itemDone", attempt: 1, id: 1, source: "direct", bytes: 3 },
      { type: "itemStart", attempt: 1, id: 2 }, { type: "cancel" }], running);
    expect(statuses(s)).toEqual(["1:done", "2:cancelled", "3:cancelled"]);
    expect(summarize(s)).toMatchObject({ failed: 0, cancelled: 2 });
  });
  it("a late itemFailed after cancel does not overwrite", () => {
    const s = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "cancel" }, { type: "itemFailed", attempt: 1, id: 1, error: "abort" }], running);
    expect(s.items[0]).toMatchObject({ status: "cancelled", error: null });
  });
  it("retryFailed requeues only the failed ones", () => {
    const s = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "itemDone", attempt: 1, id: 1, source: "direct", bytes: 3 },
      { type: "itemStart", attempt: 1, id: 2 }, { type: "itemFailed", attempt: 1, id: 2, error: "relay 502" },
      { type: "itemStart", attempt: 1, id: 3 }, { type: "itemFailed", attempt: 1, id: 3, error: "x" }], running);
    expect(s.phase).toBe("done");
    expect(canRetry(s)).toBe(true);
    const r = run([{ type: "retryFailed" }], s);
    expect(r.phase).toBe("running");
    expect(statuses(r)).toEqual(["1:done", "2:queued", "3:queued"]);
  });
  it("retryFailed with nothing failed is a no-op", () => {
    const s = run([1, 2, 3].flatMap((id): Action[] => [{ type: "itemStart", attempt: 1, id },
      { type: "itemDone", attempt: 1, id, source: "direct", bytes: 1 }]), running);
    expect(vaultDownloadReducer(s, { type: "retryFailed" })).toBe(s);
  });
  it("summarize counts sources", () => {
    const s = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "itemDone", attempt: 1, id: 1, source: "direct", bytes: 3 },
      { type: "itemStart", attempt: 1, id: 2 }, { type: "itemDone", attempt: 1, id: 2, source: "relay", bytes: 4 },
      { type: "itemStart", attempt: 1, id: 3 }], running);
    expect(summarize(s)).toEqual({ total: 3, done: 2, failed: 0, stalled: 0, cancelled: 0, drm: 0, active: 1, bytes: 7,
                                   direct: 1, relay: 1 });
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
    const s = run([{ type: "directStrike", attempt: 1 }, { type: "directStrike", attempt: 1 }], running);
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
  it("toItems: no forced folder copies into every other custom folder; a forced folder makes none", () => {
    const ls = [{ type: "custom", name: "A" }, { type: "messages", name: "M" }, { type: "custom", name: "B/x" },
                { type: "custom", name: "A" }];
    expect(toItems([media(1, "photo", null, ls)], null)[0]).toMatchObject({ folder: "A", copies: ["B_x"] });
    expect(toItems([media(1, "photo", null, ls)], "feet")[0].copies).toBeUndefined();
    expect(toItems([media(1, "photo", null, ls.slice(0, 1))], null)[0].copies).toBeUndefined();
  });
  it("toItems: DRM-only video has no url, mp4 name", () => {
    const [it0] = toItems([media(9, "video", null)], null);
    expect(it0).toMatchObject({ id: 9, url: null, name: "9.mp4", status: "queued", folder: UNFILED });
  });
});

describe("share sink (phones)", () => {
  const MB = 1 << 20;
  const B = 10 * MB;   // a small budget for the tables
  const fold = (sizes: number[], budget = B) =>
    sizes.reduce<DlBatch[]>((bs, n, i) => addToBatches(bs, i + 1, n, budget), []);
  const shape = (bs: DlBatch[]) => bs.map((b) => `${b.ids.join(",")}${b.sealed ? "|" : ""}`);

  it.each<[string, number[], string[]]>([
    ["small files share one open batch", [MB, MB, MB], ["1,2,3"]],
    ["the file that would overflow seals the batch and opens the next", [4 * MB, 4 * MB, 4 * MB], ["1,2|", "3"]],
    ["exactly the budget seals", [4 * MB, 6 * MB, MB], ["1,2|", "3"]],
    ["a file over the budget is a batch of its own", [MB, 30 * MB, MB], ["1|", "2|", "3"]],
    ["a first file over the budget seals alone", [30 * MB], ["1|"]],
    ["photos then a video > budget/2", [MB, MB, MB, 8 * MB, MB], ["1,2,3|", "4,5"]],
  ])("addToBatches: %s", (_n, sizes, want) => {
    expect(shape(fold(sizes))).toEqual(want);
  });
  it("every id lands in exactly one batch, in order", () => {
    const sizes = [3, 9, 1, 12, 2, 2, 7, 25, 1, 4].map((n) => n * MB);
    expect(fold(sizes).flatMap((b) => b.ids)).toEqual(sizes.map((_, i) => i + 1));
  });

  const shareStart: Action = { ...start, sink: "share" };
  const doneA = (id: number, bytes: number): Action[] => [{ type: "itemStart", attempt: 1, id }, { type: "itemDone", attempt: 1, id, source: "relay", bytes }];
  const doneB = (id: number): Action[] => [{ type: "itemStart", attempt: 2, id }, { type: "itemDone", attempt: 2, id, source: "relay", bytes: MB }];
  const unsavedPhone = run([shareStart, listed([1, 2]), ...doneA(1, MB), ...doneA(2, MB)]);   // done, 1 batch unsaved

  // #10: the one gate for every Download control (selection bar, rail folder item, page header). Folder sink: a busy
  // run never turns it off (the press queues); an open picker does.
  it.each<[string, DlState, DlSink | null, DlMode, number, DlAccess, string, boolean]>([
    ["no sink", initialDownloadState, null, "selection", 1, "all", DOWNLOAD_OFF, false],
    ["desktop, running: queues", running, "folder", "selection", 1, "all", "", false],
    ["picker open", run([{ type: "pick" }]), "folder", "vault", 0, "all", BUSY_OFF, false],
    ["desktop, listing: queues", run([start]), "folder", "selection", 1, "all", "", false],
    ["phone, running: names the run", run([shareStart, listed([1, 2])]), "share", "selection", 1, "all",
      `${BUSY_OFF}: amy · 0/2`, false],
    ["phone: run done, files not saved yet (not 'running')", unsavedPhone, "share", "selection", 1, "all", UNSAVED_OFF, false],
    ["phone: run done, all saved", run([{ type: "batchSaved", index: 0, attempt: 1 }], unsavedPhone), "share", "selection", 1,
      "all", "", false],
    ["desktop folder", initialDownloadState, "folder", "folder", 0, "all", "", false],
    ["desktop vault", initialDownloadState, "folder", "vault", 0, "all", "", false],
    ["desktop 500 selected", initialDownloadState, "folder", "selection", 500, "all", "", false],
    ["phone 20 selected", initialDownloadState, "share", "selection", 20, "all", "", false],
    ["phone 21 selected", initialDownloadState, "share", "selection", 21, "all", SHARE_COUNT_OFF, false],
    ["phone folder", initialDownloadState, "share", "folder", 0, "all", SHARE_MODE_OFF, true],
    ["phone vault", initialDownloadState, "share", "vault", 0, "all", SHARE_MODE_OFF, true],
    ["phone vault, restricted: desktop only first", initialDownloadState, "share", "vault", 0, "folders", SHARE_MODE_OFF, true],
    ["restricted chatter, vault", initialDownloadState, "folder", "vault", 0, "folders", RESTRICTED_OFF, false],
    ["access unread, vault", initialDownloadState, "folder", "vault", 0, "unknown", RESTRICTED_OFF, false],
    ["restricted chatter, folder", initialDownloadState, "folder", "folder", 0, "folders", "", false],
    ["restricted chatter, selection", initialDownloadState, "folder", "selection", 3, "folders", "", false],
    ["a finished run", run([{ type: "cancel" }], running), "folder", "vault", 0, "all", "", false],
  ])("downloadGate: %s", (_n, st, sink, mode, count, access, reason, desktopOnly) => {
    expect(downloadGate(st, sink, mode, count, access)).toEqual({ reason, desktopOnly });
  });
  it.each<[string, Parameters<typeof dlAccess>[0], DlAccess]>([
    ["owner (query disabled)", { isLoading: false, isError: false }, "all"],
    ["unrestricted chatter", { isLoading: false, isError: false, data: { restricted: false } }, "all"],
    ["restricted chatter", { isLoading: false, isError: false, data: { restricted: true } }, "folders"],
    ["not read yet", { isLoading: true, isError: false }, "unknown"],
    ["read failed", { isLoading: false, isError: true }, "unknown"],
  ])("dlAccess: %s", (_n, q, want) => {
    expect(dlAccess(q)).toBe(want);
  });
  // #6: unsaved phone files are never dropped by a new run or a plain close.
  it.each<[string, DlState, boolean]>([
    ["idle", initialDownloadState, false],
    ["picker open", run([{ type: "pick" }]), true],
    ["running", running, true],
    ["phone, fetched files unsaved", unsavedPhone, true],
    ["phone, all saved", run([{ type: "batchSaved", index: 0, attempt: 1 }], unsavedPhone), false],
  ])("holdsFiles: %s", (_n, st, want) => {
    expect(holdsFiles(st)).toBe(want);
  });
  it("unsaved phone files: start and close are refused; close with discard drops them", () => {
    expect(vaultDownloadReducer(unsavedPhone, start)).toBe(unsavedPhone);
    expect(vaultDownloadReducer(unsavedPhone, { type: "close" })).toBe(unsavedPhone);
    const gone = vaultDownloadReducer(unsavedPhone, { type: "close", discard: true });
    expect([gone.phase, gone.batches.length, gone.attempt]).toEqual(["idle", 0, unsavedPhone.attempt]);
  });
  it("discard is refused while the run is still going", () => {
    expect(vaultDownloadReducer(running, { type: "close", discard: true })).toBe(running);
  });
  it("done files fill batches; the run's end seals the open one; save marks it", () => {
    const s0 = run([shareStart, listed([1, 2, 3])]);
    const s1 = run([...doneA(1, MB), ...doneA(2, SHARE_BATCH_BYTES)], s0);
    expect(shape(s1.batches)).toEqual(["1|", "2|"]);
    expect(readyBatch(s1)).toBe(0);
    expect(batchLabel(s1, 0)).toBe("Save 1");
    const s2 = run([{ type: "itemStart", attempt: 1, id: 3 }, { type: "itemFailed", attempt: 1, id: 3, error: "DRM" }], s1);
    expect(s2.phase).toBe("done");
    expect(shape(s2.batches)).toEqual(["1|", "2|"]);
    const s3 = run([{ type: "batchSaved", index: 0, attempt: 1 }], s2);
    expect(readyBatch(s3)).toBe(1);
    expect(batchLabel(s3, 1)).toBe("Save 2");
    expect(unsaved(s3)).toBe(1);
    expect(run([{ type: "batchSaved", index: 0, attempt: 1 }], s3)).toBe(s3);   // twice is a no-op
  });
  // slop phone stage: 3 photos + 2 videos each > SHARE_BATCH_BYTES / 2 (110 MiB of 200): 2 batches, all 5 land.
  it("phone: photos + 2 videos > budget/2 make 2 batches; every item lands once and the run ends done", () => {
    const sizes: [number, number][] = [[3, 180_000], [4, 190_000], [6, 140_000], [8, 110 * MB], [11, 110 * MB]];
    const s = run([shareStart, listed(sizes.map(([id]) => id)), ...sizes.flatMap(([id, n]) => doneA(id, n))]);
    expect(s.phase).toBe("done");
    expect(shape(s.batches)).toEqual(["3,4,6,8|", "11|"]);
    expect(s.batches.flatMap((b) => b.ids)).toEqual([3, 4, 6, 8, 11]);
    expect(summarize(s)).toMatchObject({ total: 5, done: 5, failed: 0, stalled: 0, cancelled: 0, drm: 0 });
    expect([batchLabel(s, 0), batchLabel(s, 1), unsaved(s)]).toEqual(["Save 1–4", "Save 5", 5]);
    const saved = run([{ type: "batchSaved", index: 0, attempt: 1 }, { type: "batchSaved", index: 1, attempt: 1 }], s);
    expect([unsaved(saved), countText(saved)]).toEqual([0, "5 of 5 ready · 5 saved"]);
  });
  // #38: a share sheet of a discarded run that resolves late never marks the new run's batch saved.
  it.each<[string, number, boolean]>([
    ["this run's sheet saves its batch", 2, true],
    ["an older run's late sheet changes nothing", 1, false],
  ])("batchSaved: %s", (_n, attempt, saved) => {
    const discarded = run([{ type: "close", discard: true }], unsavedPhone);
    const second = run([shareStart, listed([1, 2], 2), ...doneB(1), ...doneB(2)], discarded);
    expect([second.attempt, readyBatch(second)]).toEqual([2, 0]);
    expect(run([{ type: "batchSaved", index: 0, attempt }], second).batches[0].saved).toBe(saved);
  });
  it("an open batch can't be saved; the folder sink never batches", () => {
    const s = run([shareStart, listed([1, 2]), ...doneA(1, MB)]);
    expect(readyBatch(s)).toBe(-1);
    expect(run([{ type: "batchSaved", index: 0, attempt: 1 }], s)).toBe(s);
    expect(run([start, listed([1]), ...doneA(1, MB)]).batches).toEqual([]);
  });
  it("cancel seals what was fetched so it can still be saved", () => {
    const s = run([shareStart, listed([1, 2, 3]), ...doneA(1, MB), ...doneA(2, MB), { type: "cancel" }]);
    expect(shape(s.batches)).toEqual(["1,2|"]);
    expect(batchLabel(s, 0)).toBe("Save 1–2");
  });
  it("canFetchMore holds the share sink at ~2 batches unsaved, never the folder sink", () => {
    const half = SHARE_HELD_BYTES / 2;
    const bs = (n: number, saved = false): DlBatch => ({ ids: [1], bytes: n, sealed: true, saved });
    expect(canFetchMore({ sink: "share", batches: [bs(half)] })).toBe(true);
    expect(canFetchMore({ sink: "share", batches: [bs(half), bs(half)] })).toBe(false);
    expect(canFetchMore({ sink: "share", batches: [bs(half, true), bs(half)] })).toBe(true);
    expect(canFetchMore({ sink: "folder", batches: [bs(SHARE_HELD_BYTES * 9)] })).toBe(true);
    expect(heldBytes({ batches: [bs(5, true), bs(7)] })).toBe(7);
  });
  it.each<[string, string]>([
    ["1.jpg", "image/jpeg"], ["2.JPEG", "image/jpeg"], ["3.png", "image/png"], ["4.gif", "image/gif"],
    ["5.mp4", "video/mp4"], ["6.mov", "video/quicktime"], ["7.mp3", "audio/mpeg"], ["8.bin", "application/octet-stream"],
  ])("mimeFor(%s) = %s", (name, want) => {
    expect(mimeFor(name)).toBe(want);
  });
  it("title + count read 'ready' until the share resolves, 'saved' after (not 'Downloaded' before a tap)", () => {
    const fetched = run([shareStart, listed([1, 2]), ...doneA(1, 150 * MB), ...doneA(2, 150 * MB)]);
    expect(fetched.phase).toBe("done");
    expect(panelTitle(fetched)).toBe("Ready to save: amy: 3 selected");
    expect(countText(fetched)).toBe("2 of 2 ready");
    const one = run([{ type: "batchSaved", index: 0, attempt: 1 }], fetched);
    expect(panelTitle(one)).toBe("Ready to save: amy: 3 selected");
    expect(countText(one)).toBe("2 of 2 ready · 1 saved");
    const all = run([{ type: "batchSaved", index: 1, attempt: 1 }], one);
    expect(panelTitle(all)).toBe("Saved amy: 3 selected");
    expect(countText(all)).toBe("2 of 2 ready · 2 saved");
    const folder = run([start, listed([1]), ...doneA(1, MB)]);
    expect(panelTitle(folder)).toBe("Downloaded amy: 3 selected");
    // the run's creator once, from the state (the label stays raw: the links file adds the creator itself)
    expect([run([start]), running, run([{ type: "cancel" }], running)].map(panelTitle))
      .toEqual(["Listing amy: 3 selected…", "Downloading amy: 3 selected", "Cancelled: amy: 3 selected"]);
    expect(running.label).toBe("3 selected");
    expect(countText(folder)).toBe("1 of 1 saved");
  });
  // #4: the title says what happened, never "Downloaded" / "Saved" with nothing saved.
  const failA = (id: number): Action[] => [{ type: "itemStart", attempt: 1, id }, { type: "itemFailed", attempt: 1, id, error: "x" }];
  it.each<[string, Action[], string]>([
    ["folder: listing failed", [start, { type: "runError", error: "relay 500", attempt: 1 }], "Download failed: amy: 3 selected"],
    ["folder: nothing listed", [start, listed([])], "Nothing to download: amy: 3 selected"],
    ["folder: every item failed", [start, listed([1, 2]), ...failA(1), ...failA(2)], "Nothing saved: amy: 3 selected"],
    ["folder: some failed", [start, listed([1, 2]), ...doneA(1, MB), ...failA(2)], "Partly downloaded: amy: 3 selected"],
    ["folder: all saved", [start, listed([1]), ...doneA(1, MB)], "Downloaded amy: 3 selected"],
    ["share: every item failed", [shareStart, listed([1, 2]), ...failA(1), ...failA(2)], "Nothing saved: amy: 3 selected"],
    ["share: fetched, not saved", [shareStart, listed([1]), ...doneA(1, MB)], "Ready to save: amy: 3 selected"],
    ["share: saved, one failed", [shareStart, listed([1, 2]), ...doneA(1, MB), ...failA(2),
      { type: "batchSaved", index: 0, attempt: 1 }], "Partly saved: amy: 3 selected"],
    ["share: listing failed", [shareStart, { type: "runError", error: "x", attempt: 1 }], "Download failed: amy: 3 selected"],
    ["cancelled", [start, { type: "cancel" }], "Cancelled: amy: 3 selected"],
  ])("panelTitle: %s", (_n, actions, want) => {
    expect(panelTitle(run(actions))).toBe(want);
  });
  // #9: the desktop links file's outcome is recorded; the phone's only on a resolved share.
  it.each<[string, Action[], string]>([
    ["share sink, sheet resolved", [shareStart, listed([1]), { type: "links", ok: true, attempt: 1 }], "saved"],
    ["share sink, sheet dismissed", [shareStart, listed([1]), { type: "links", ok: false, attempt: 1 }], "none"],
    ["folder sink, written", [start, listed([1]), { type: "links", ok: true, attempt: 1 }], "saved"],
    ["folder sink, write failed", [start, listed([1]), { type: "links", ok: false, attempt: 1 }], "failed"],
    ["nothing listed yet: no-op", [shareStart, { type: "links", ok: true, attempt: 1 }], "none"],
    ["an older run's links: no-op", [shareStart, listed([1]), { type: "cancel" }, { type: "close" }, shareStart,
      listed([1], 2), { type: "links", ok: true, attempt: 1 }], "none"],
    ["a new run clears it", [shareStart, listed([1]), ...doneA(1, MB), { type: "links", ok: true, attempt: 1 },
      { type: "batchSaved", index: 0, attempt: 1 }, { type: "close" }, shareStart], "none"],
  ])("links: %s", (_n, actions, want) => {
    expect(run(actions).links).toBe(want);
  });
});

describe("outcomes: failed / stalled / drm / cancelled", () => {
  const fin = (id: number, reason?: "failed" | "stalled" | "drm"): Action[] =>
    [{ type: "itemStart", attempt: 1, id }, { type: "itemFailed", attempt: 1, id, error: "x", ...(reason ? { reason } : {}) }];
  const ok = (id: number): Action[] => [{ type: "itemStart", attempt: 1, id },
    { type: "itemDone", attempt: 1, id, source: "relay", bytes: 1 }];
  const mixed = run([start, listed([1, 2, 3, 4, 5]), ...ok(1), ...fin(2, "stalled"), ...fin(3, "drm"), ...fin(4),
                     ...fin(5, "failed")]);

  it("each reason is its own status; no reason is failed", () => {
    expect(statuses(mixed)).toEqual(["1:done", "2:stalled", "3:drm", "4:failed", "5:failed"]);
    expect(summarize(mixed)).toMatchObject({ done: 1, stalled: 1, drm: 1, failed: 2, cancelled: 0 });
  });
  it("title: partly when any item has no file; DRM is never 'failed'", () => {
    expect(panelTitle(mixed)).toBe("Partly downloaded: amy: 3 selected");
    expect(panelTitle(run([start, listed([1, 2]), ...ok(1), ...fin(2, "drm")]))).toBe("Partly downloaded: amy: 3 selected");
    expect(outcomeParts(summarize(mixed))).toEqual([
      { text: "1 stalled", bad: true }, { text: "2 failed", bad: true }, { text: "1 DRM (no file)", bad: false }]);
  });
  it("retry requeues failed + stalled, never DRM", () => {
    expect(retryable(mixed)).toBe(3);
    expect(statuses(run([{ type: "retryFailed" }], mixed)))
      .toEqual(["1:done", "2:queued", "3:drm", "4:queued", "5:queued"]);
  });
  it("only DRM left: nothing to retry", () => {
    const s = run([start, listed([1, 2]), ...ok(1), ...fin(2, "drm")]);
    expect(canRetry(s)).toBe(false);
    expect(vaultDownloadReducer(s, { type: "retryFailed" })).toBe(s);
  });
  it("cancelled items are retryable", () => {
    const s = run([{ type: "cancel" }], running);
    expect(canRetry(s)).toBe(true);
    expect(statuses(run([{ type: "retryFailed" }], s))).toEqual(["1:queued", "2:queued", "3:queued"]);
  });
  it("progressText names the run and how far", () => {
    expect(progressText(run([start]))).toBe("amy · listing");
    expect(progressText(run([...ok(1)], running))).toBe("amy · 1/3");
    expect(busyOff(running)).toBe(`${BUSY_OFF}: amy · 0/3`);
  });
});

// Hard invariant: `done` only once every item has its outcome. A seeded walk over every item event, both sinks.
describe("invariant: a run is done only when every item has an outcome", () => {
  const OUTCOME = new Set(["done", "failed", "stalled", "cancelled", "drm"]);
  it.each<[string, DlSink, number]>([
    ["folder sink", "folder", 1], ["folder sink", "folder", 2], ["share sink", "share", 3], ["share sink", "share", 4],
  ])("%s %s, seed %d: after every step, phase done implies no queued / active item", (_n, sink, seed) => {
    let x = seed;
    const rnd = (n: number) => { x = (x * 1103515245 + 12345) % 2147483648; return (x >>> 16) % n; };
    let s = run([{ ...start, sink }, listed([1, 2, 3, 4, 5, 6])]);
    let dones = 0;
    for (let step = 0; step < 400; step++) {
      const id = 1 + rnd(6);
      const pick = rnd(10);
      const a: Action = pick < 3 ? { type: "itemStart", attempt: s.attempt, id }
        : pick < 6 ? { type: "itemDone", attempt: s.attempt, id, source: "relay", bytes: (1 + rnd(150)) << 20 }
        : pick < 8 ? { type: "itemFailed", attempt: s.attempt, id, error: "x",
                       reason: (["failed", "stalled", "drm"] as const)[rnd(3)] }
        : pick < 9 ? { type: "retryFailed" }
        : { type: "itemProgress", attempt: s.attempt, id, bytes: 1 };
      s = vaultDownloadReducer(s, a);
      if (s.phase === "done") {
        dones += 1;
        expect(s.items.filter((i) => !OUTCOME.has(i.status)).map((i) => `${i.id}:${i.status}`)).toEqual([]);
        if (sink === "share") {   // every done item in exactly one batch, nothing else
          expect(s.batches.flatMap((b) => b.ids).sort()).toEqual(
            s.items.filter((i) => i.status === "done").map((i) => i.id).sort());
        }
      }
    }
    expect(dones).toBeGreaterThan(0);
  });
  it("runError and cancel close every open item before the run ends", () => {
    const errored = run([{ type: "itemStart", attempt: 1, id: 1 }, { type: "runError", error: "boom", attempt: 1 }], running);
    expect([errored.phase, statuses(errored)]).toEqual(["done", ["1:failed", "2:failed", "3:failed"]]);
    const cancelled = run([{ type: "cancel" }], running);
    expect(statuses(cancelled).every((t) => t.endsWith(":cancelled"))).toBe(true);
  });
});

const finishAll = (s: DlState): DlState => run(s.items.flatMap((i): Action[] => [
  { type: "itemStart", attempt: s.attempt, id: i.id },
  { type: "itemDone", attempt: s.attempt, id: i.id, source: "relay", bytes: 1 }]), s);

describe("queue (folder sink)", () => {
  const job = (accountId: string, creator: string, mode: DlMode = "folder", folderId: number | null = 7): DlJobArgs => ({
    accountId, creator, mode, label: mode === "vault" ? "whole vault" : `folder f${folderId}`, source: "mirror",
    folder: mode === "folder" ? { id: folderId!, name: `f${folderId}` } : null,
  });
  const enq = (j: DlJobArgs): Action => ({ type: "enqueue", job: j });
  const withQueue = run([enq(job("acc-bea", "bea")), enq(job("acc-cat", "cat", "vault"))], running);

  it("enqueue only while a run is busy (or jobs wait): idle refuses, the share sink never queues", () => {
    expect(vaultDownloadReducer(initialDownloadState, enq(job("acc-bea", "bea")))).toBe(initialDownloadState);
    const phone = run([{ ...start, sink: "share" }, listed([1])]);
    expect(vaultDownloadReducer(phone, enq(job("acc-bea", "bea")))).toBe(phone);
    expect(withQueue.jobs.map((j) => [j.qid, j.creator])).toEqual([[2, "bea"], [3, "cat"]]);
  });
  it.each<[string, DlJobArgs, number]>([
    ["the same folder of the same model again", job("acc-bea", "bea"), 2],
    ["the same whole vault again", job("acc-cat", "cat", "vault"), 2],
    ["another folder of a queued model", job("acc-bea", "bea", "folder", 8), 3],
    ["a selection (never a duplicate)", { ...job("acc-bea", "bea", "selection"), media: [media(1)] }, 3],
  ])("dedupe: %s -> %s queued", (_n, j, n) => {
    expect(run([enq(j)], withQueue).jobs.length).toBe(n);
  });
  it("the running job itself is not queued again", () => {
    const folderRun = run([{ ...start, mode: "folder", folder: { id: 5, name: "f5" } }, listed([1])]);
    expect(run([enq({ ...job("acc-amy", "amy", "folder", 5) })], folderRun).jobs).toEqual([]);
  });
  it("queues / canQueue: busy or waiting, folder sink only", () => {
    expect([initialDownloadState, running, withQueue, finishAll(withQueue)].map(canQueue)).toEqual([false, true, true, true]);
    expect(queues("share", running)).toBe(false);
    expect(queues(null, running)).toBe(false);
    expect(queues("folder", running)).toBe(true);
  });
  it("the head starts by qid when the run settles; its run is its own creator; the last run goes to finished", () => {
    const done = finishAll(withQueue);
    expect(done.phase).toBe("done");
    const next = run([{ type: "start", mode: "folder", label: "folder f7", accountId: "acc-bea", creator: "bea",
                        folder: { id: 7, name: "f7" }, qid: 2 }], done);
    expect(next).toMatchObject({ phase: "listing", accountId: "acc-bea", creator: "bea", jobId: 4, attempt: 2,
                                 folder: { id: 7, name: "f7" } });
    expect(next.jobs.map((j) => j.qid)).toEqual([3]);
    expect(next.finished).toEqual([{ jobId: 1, accountId: "acc-amy", creator: "amy", title: "Downloaded amy: 3 selected",
                                     total: 3, done: 3, failed: 0, stalled: 0, cancelled: 0, drm: 0 }]);
  });
  it("the old run's late events never touch the next one (attempt)", () => {
    const next = run([{ type: "start", mode: "folder", label: "folder f7", accountId: "acc-bea", creator: "bea",
                        qid: 2 }, listed([1], 2)], run([{ type: "cancel" }], withQueue));
    expect(next.phase).toBe("running");
    expect(run([{ type: "itemStart", attempt: 1, id: 1 }], next)).toBe(next);
  });
  it("a start for a qid no longer queued (Clear queue meanwhile) is refused", () => {
    const cleared = run([{ type: "clearQueue" }], finishAll(withQueue));
    expect(cleared.jobs).toEqual([]);
    const a: Action = { type: "start", mode: "folder", label: "x", accountId: "acc-bea", creator: "bea", qid: 2 };
    expect(vaultDownloadReducer(cleared, a)).toBe(cleared);
  });
  it("finished keeps the last FINISHED_MAX runs", () => {
    let s = running;
    for (let i = 0; i < FINISHED_MAX + 2; i++) {
      const f = finishAll(s);
      s = run([start, listed([1], f.attempt + 1)], f);
    }
    expect(s.finished.length).toBe(FINISHED_MAX);
    expect(s.finished[FINISHED_MAX - 1].jobId).toBe(s.jobId - 1);
  });
  it("cancel (current) keeps the queue; stop cancels and drops it", () => {
    const c = run([{ type: "cancel" }], withQueue);
    expect(c).toMatchObject({ phase: "cancelled" });
    expect(c.jobs.length).toBe(2);
    const st = run([{ type: "stop" }], withQueue);
    expect(st).toMatchObject({ phase: "cancelled", jobs: [], paused: false });
    expect(vaultDownloadReducer(initialDownloadState, { type: "stop" })).toBe(initialDownloadState);
  });
  it("paused only with jobs waiting and nothing busy; resumed lifts it; close keeps the waiting queue", () => {
    expect(vaultDownloadReducer(withQueue, { type: "paused" })).toBe(withQueue);   // busy
    const p = run([{ type: "paused" }], finishAll(withQueue));
    expect(p.paused).toBe(true);
    expect(canQueue(p)).toBe(true);
    const closed = run([{ type: "close" }], p);
    expect(closed).toMatchObject({ phase: "idle", paused: true, seq: 3, attempt: 1 });
    expect(closed.jobs.length).toBe(2);
    expect(run([{ type: "resumed" }], closed).paused).toBe(false);
    expect(run([{ type: "clearQueue" }], closed)).toMatchObject({ jobs: [], paused: false });
  });
  it("keepAccounts: a removed model's run is cancelled and its queued jobs dropped; others stay", () => {
    const s = run([{ type: "keepAccounts", ids: ["acc-cat"] }], withQueue);
    expect(s.phase).toBe("cancelled");
    expect(s.jobs.map((j) => j.creator)).toEqual(["cat"]);
    const all = ["acc-amy", "acc-bea", "acc-cat"];
    expect(vaultDownloadReducer(withQueue, { type: "keepAccounts", ids: all })).toBe(withQueue);
    const onlyAmy = run([{ type: "keepAccounts", ids: ["acc-amy"] }], withQueue);
    expect(onlyAmy).toMatchObject({ phase: "running", jobs: [] });
  });
  it("title: 'Download queue' with no card but jobs waiting", () => {
    const closed = run([{ type: "paused" }, { type: "close" }], finishAll(withQueue));
    expect(panelTitle(closed)).toBe("Download queue");
  });
});

describe("retry jobs (a run a queued job replaces keeps its Retry)", () => {
  const enq: Action = { type: "enqueue", job: { accountId: "acc-bea", creator: "bea", mode: "folder", label: "folder f7",
                                                source: "mirror", folder: { id: 7, name: "f7" } } };
  const end = (outs: Record<number, "done" | "failed" | "stalled" | "drm">, from: DlState): DlState =>
    run(Object.entries(outs).flatMap(([id, o]): Action[] => [{ type: "itemStart", attempt: from.attempt, id: +id },
      o === "done" ? { type: "itemDone", attempt: from.attempt, id: +id, source: "relay", bytes: 1 }
        : { type: "itemFailed", attempt: from.attempt, id: +id, error: o, reason: o }]), from);
  const four = run([start, listed([1, 2, 3, 4])]);

  it.each<[string, DlState, Record<number, "done" | "failed" | "stalled" | "drm">, number[] | null]>([
    ["failed + stalled while a job waits: one retry job of exactly those (DRM skipped)", run([enq], four),
     { 1: "done", 2: "failed", 3: "stalled", 4: "drm" }, [2, 3]],
    ["all done while a job waits: no retry job", run([enq], four), { 1: "done", 2: "done", 3: "done", 4: "done" }, null],
    ["only DRM short: no retry job", run([enq], four), { 1: "done", 2: "drm", 3: "done", 4: "done" }, null],
    ["a failure, no job waiting: none (the card's own Retry stays)", four, { 1: "failed", 2: "done", 3: "done", 4: "done" }, null],
  ])("%s", (_n, from, outs, want) => {
    const s = end(outs, from);
    expect(s.phase).toBe("done");
    const retry = s.jobs.filter((j) => j.retryOf != null);
    if (want === null) {
      expect(retry).toEqual([]);
      return;
    }
    expect(retry).toHaveLength(1);
    expect(retry[0]).toMatchObject({ accountId: "acc-amy", creator: "amy", mode: "selection", retryOf: s.jobId,
                                     label: `3 selected · retry ${want.length}`, qid: s.seq });
    expect(retry[0].items!.map((i) => [i.id, i.status, i.error])).toEqual(want.map((id) => [id, "queued", null]));
    expect(s.jobs[0].creator).toBe("bea");   // the waiting job stays first
    expect(canRetry(s)).toBe(false);          // already queued: no second Retry
  });
  it("a run that threw while a job waits: its failed items join the queue as a retry job too", () => {
    const s = run([enq, { type: "runError", error: "boom", attempt: 1 }], four);
    expect(s.jobs.map((j) => j.retryOf ?? null)).toEqual([null, s.jobId]);
  });
  it.each<[string, "done" | "failed", string[]]>([
    ["B all done: A's retry is the only job left", "done", ["amy"]],
    ["B fails too: A's retry first, B's own behind it", "failed", ["amy", "bea"]],
  ])("A stalls -> B starts and settles -> A's retry runs last: %s", (_n, bOut, retriesAfterB) => {
    const head = (s: DlState): Action => {
      const j = s.jobs[0];
      return { type: "start", mode: j.mode, label: j.label, accountId: j.accountId, creator: j.creator,
               folder: j.folder ?? null, qid: j.qid };
    };
    const a = end({ 1: "done", 2: "stalled", 3: "done" }, run([enq], running));
    expect(a.jobs.map((j) => [j.creator, j.retryOf ?? null])).toEqual([["bea", null], ["amy", a.jobId]]);
    const b = end({ 7: "done", 8: bOut }, run([head(a), listed([7, 8], a.attempt + 1)], a));
    expect(b).toMatchObject({ creator: "bea", phase: "done" });
    expect(b.jobs.map((j) => j.creator)).toEqual(retriesAfterB);
    expect(b.jobs.every((j) => j.retryOf != null)).toBe(true);
    const r = run([head(b), { type: "listed", items: b.jobs[0].items!, attempt: b.attempt + 1 }], b);
    expect(r).toMatchObject({ phase: "running", creator: "amy", label: "3 selected · retry 1" });
    expect(r.items.map((i) => [i.id, i.status])).toEqual([[2, "queued"]]);
    expect(r.finished.map((f) => [f.creator, f.stalled, f.failed])).toEqual([["amy", 1, 0], ["bea", 0, bOut === "failed" ? 1 : 0]]);
    expect(r.jobs).toHaveLength(retriesAfterB.length - 1);
  });
  it("the share sink never queues a retry job", () => {
    const phone = run([{ ...start, sink: "share" }, listed([1])]);
    expect(retryJobOf(end({ 1: "failed" }, phone))).toBeNull();
  });
  it("retryLater: the retry waits as a job behind Resume (paused); nothing to retry: unchanged", () => {
    const later = run([{ type: "retryLater" }], end({ 1: "failed", 2: "done", 3: "done" }, running));
    expect(later).toMatchObject({ paused: true, phase: "done" });
    expect(later.jobs.map((j) => j.items!.map((i) => i.id))).toEqual([[1]]);
    expect(canRetry(later)).toBe(false);
    const clean = end({ 1: "done", 2: "done", 3: "done" }, running);
    expect(vaultDownloadReducer(clean, { type: "retryLater" })).toBe(clean);
  });
  it.each<[string, DlState, string[], boolean]>([
    ["a finished run of a removed model: the card goes (no Retry left)", run([{ type: "itemStart", attempt: 1, id: 1 },
      { type: "itemFailed", attempt: 1, id: 1, error: "x" }, { type: "cancel" }], running), ["acc-bea"], true],
    ["a finished run of a kept model stays", run([{ type: "cancel" }], running), ["acc-amy"], false],
  ])("keepAccounts: %s", (_n, from, ids, gone) => {
    const s = vaultDownloadReducer(from, { type: "keepAccounts", ids });
    if (gone) {
      expect(s).toMatchObject({ phase: "idle", items: [], seq: from.seq, attempt: from.attempt });
      expect(canRetry(s)).toBe(false);
    } else expect(s).toBe(from);
  });
});
