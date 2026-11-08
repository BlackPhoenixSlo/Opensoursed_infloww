import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";

const h = vi.hoisted(() => ({
  describeMedia: vi.fn(), addToOfFolder: vi.fn(), createOfFolder: vi.fn(),
  startCollect: vi.fn(), fetchCollectStatus: vi.fn(),
}));
vi.mock("@/hooks/useVaultCache", async (orig) => ({
  ...(await orig<typeof import("@/hooks/useVaultCache")>()),
  describeMedia: h.describeMedia,
  addToOfFolder: h.addToOfFolder,
  createOfFolder: h.createOfFolder,
  startCollect: h.startCollect,
  fetchCollectStatus: h.fetchCollectStatus,
}));

import {
  addSelectedToFolder,
  collectHasNews,
  describeOne,
  describeSelected,
  newFolderWithSelection,
  onCollect,
  type ManageDeps,
  type Tile,
} from "./vaultManageActions";

/** A busy line backed by a plain variable, like the panel's ref; `seen` is every value it was set to. */
function deps(selected: number[] = [1, 2]) {
  let line = "";
  const seen: string[] = [];
  const d: ManageDeps & { setPreview: (t: Tile) => void } = {
    accountId: "1000001",
    qc: new QueryClient(),
    busy: { get: () => line, set: (s) => { line = s; seen.push(s); } },
    selected: new Set(selected),
    clearSelection: vi.fn(),
    refreshAll: vi.fn(),
    capReason: "cap",
    refetchPlan: vi.fn(),
    setPreview: vi.fn(),
  };
  return { d, seen, line: () => line };
}

const tile = { id: 7, type: "photo" } as Tile;

// Collect's poll refreshes the grid once the run has news. A restricted chatter gets null totals (whole-vault), so
// "seen > 0" alone never fired for it: the grid stayed stale after Collect.
describe("collectHasNews", () => {
  const run = (total_seen: number | null, phase: string | null, status = "running") =>
    ({ id: 1, status, phase, total_seen, upserted: total_seen, pages_done: total_seen, error: null,
       started_at: null, finished_at: null, running: status === "running" });
  it.each<[string, Parameters<typeof collectHasNews>[0], boolean]>([
    ["no run", null, false],
    ["owner, paging, nothing yet", run(0, "media"), false],
    ["owner, paging, seen some", run(100, "media"), true],
    ["chatter, paging", run(null, "media"), false],
    ["chatter, past paging (thumbs)", run(null, "thumbs"), true],
    ["chatter, warm phase", run(null, "images"), true],
    ["chatter, run ended", run(null, "media", "error"), true],
    ["chatter, done", run(null, "done", "done"), true],
  ])("%s", (_, r, want) => {
    expect(collectHasNews(r)).toBe(want);
  });
});

// The poll refreshes the grid once: on news, else on its last poll (a restricted chatter's vault still paging OF
// after the window has no news it can see, and its grid would stay stale).
describe("onCollect", () => {
  const run = (total_seen: number | null, phase: string) =>
    ({ id: 1, status: "running", phase, total_seen, upserted: null, pages_done: null, error: null,
       started_at: null, finished_at: null, running: true });
  it.each<[string, ReturnType<typeof run>[], number]>([
    ["owner, news on poll 2", [run(0, "media"), run(100, "media")], 2],
    ["chatter, still paging after the window", [run(null, "media")], 4],
  ])("%s", async (_, runs, polls) => {
    vi.useFakeTimers();
    try {
      h.startCollect.mockResolvedValue(undefined);
      h.fetchCollectStatus.mockReset();
      runs.forEach((r) => h.fetchCollectStatus.mockResolvedValueOnce({ run: r }));
      h.fetchCollectStatus.mockResolvedValue({ run: runs[runs.length - 1] });
      const { d } = deps();
      const p = onCollect({ ...d, isCollecting: false });
      await vi.runAllTimersAsync();
      await p;
      expect(h.fetchCollectStatus).toHaveBeenCalledTimes(polls);
      expect(d.refreshAll).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

/** A describe that answers only when told to, so two calls can overlap. */
function heldDescribe() {
  const release: (() => void)[] = [];
  h.describeMedia.mockImplementation(
    (_a: string, id: number) =>
      new Promise((r) => release.push(() => r({ media_id: id, ok: true, status: "described" }))),
  );
  return () => release.splice(0).forEach((f) => f());
}

beforeEach(() => {
  h.describeMedia.mockReset();
  h.addToOfFolder.mockReset().mockResolvedValue({});
  h.createOfFolder.mockReset().mockResolvedValue({});
});

// Describe is a paid LLM call: a second press while one is in flight must not buy a second answer. The panel's
// buttons are `disabled={!!busy}`, but that only lands on the next render; the busy line is read synchronously.
describe("a describe while busy fires nothing", () => {
  type Fire = (d: ReturnType<typeof deps>["d"]) => Promise<void>[];
  it.each<[string, Fire]>([
    ["describeOne twice", (d) => [describeOne(tile, d), describeOne(tile, d)]],
    ["describeSelected twice", (d) => [describeSelected(d), describeSelected(d)]],
    ["describeOne then describeSelected", (d) => [describeOne(tile, d), describeSelected(d)]],
    ["describeSelected then describeOne", (d) => [describeSelected(d), describeOne(tile, d)]],
  ])("%s -> one describe call", async (_, fire) => {
    const answer = heldDescribe();
    const { d, line } = deps([1]);
    const runs = fire(d);
    expect(h.describeMedia).toHaveBeenCalledTimes(1);
    answer();
    await Promise.all(runs);
    expect(h.describeMedia).toHaveBeenCalledTimes(1);
    expect(line()).toBe("");
  });

  it("a second describe after the first settled does fire", async () => {
    h.describeMedia.mockResolvedValue({ media_id: 7, ok: true, status: "described" });
    const { d } = deps();
    await describeOne(tile, d);
    await describeOne(tile, d);
    expect(h.describeMedia).toHaveBeenCalledTimes(2);
  });
});

describe("the busy line", () => {
  it("describeSelected counts up, then clears, the ticks and the line", async () => {
    h.describeMedia.mockResolvedValue({ media_id: 1, ok: true, status: "described" });
    const { d, seen } = deps([1, 2, 3]);
    await describeSelected(d);
    expect(seen).toEqual(["describing 0/3", "describing 1/3", "describing 2/3", ""]);
    expect(h.describeMedia.mock.calls.map((c) => c[1])).toEqual([1, 2, 3]);
    expect(d.clearSelection).toHaveBeenCalledTimes(1);
  });

  it("describeSelected stops at the cap and says so", async () => {
    h.describeMedia.mockResolvedValueOnce({ media_id: 1, ok: true, status: "described" })
      .mockResolvedValueOnce({ media_id: 2, ok: false, status: "capped", detail: "spent" });
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    const { d } = deps([1, 2, 3]);
    await describeSelected(d);
    expect(h.describeMedia).toHaveBeenCalledTimes(2);
    expect(d.refetchPlan).toHaveBeenCalledTimes(1);
    expect(alert).toHaveBeenCalledWith("spent\n\nDescribed 1 of 3 before the cap.");
    alert.mockRestore();
  });

  it("add-to-folder while busy sends nothing; once free it sends the ticks and clears", async () => {
    const { d } = deps([4, 5]);
    d.busy.set("describing");
    await addSelectedToFolder(9, d);
    expect(h.addToOfFolder).not.toHaveBeenCalled();
    d.busy.set("");
    await addSelectedToFolder(9, d);
    expect(h.addToOfFolder).toHaveBeenCalledWith("1000001", 9, [4, 5]);
    expect(d.clearSelection).toHaveBeenCalledTimes(1);
    expect(d.refreshAll).toHaveBeenCalledTimes(1);
  });

  it("new folder while busy asks nothing", async () => {
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("Beach");
    const { d } = deps([4]);
    d.busy.set("adding to OF…");
    await newFolderWithSelection(d);
    expect(prompt).not.toHaveBeenCalled();
    d.busy.set("");
    await newFolderWithSelection(d);
    expect(h.createOfFolder).toHaveBeenCalledWith("1000001", "Beach", [4]);
    prompt.mockRestore();
  });
});
