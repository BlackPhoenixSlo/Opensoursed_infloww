import { describe, expect, it } from "vitest";

import { platformHonours, type ChatListFilter } from "@/lib/chatFilters";
import type { Platform } from "@/lib/platform";

import type { ActiveChip } from "./FanListFilters";
import { fanListChips, type FanListChipSet } from "./fanListChips";

const OF: Platform[] = ["onlyfans"];
const FS: Platform[] = ["fansly"];
const MIXED: Platform[] = ["fansly", "onlyfans"];
const NONE: Platform[] = [];

const b = (key: Extract<ActiveChip, { kind: "builtin" }>["key"]): ActiveChip => ({ kind: "builtin", key });
const folder = (listId: string): ActiveChip => ({ kind: "folder", listId });
const ALL = b("all");

const set = (pinned: boolean, tips: boolean, unreadTips: boolean, priority: boolean): FanListChipSet =>
  ({ pinned, who_tipped: tips, unread_tips: unreadTips, priority });

describe("fanListChips: visible chips", () => {
  it.each<[string, Platform[], boolean, FanListChipSet]>([
    ["OnlyFans, tips off", OF, false, set(true, true, false, true)],
    ["OnlyFans, tips on", OF, true, set(true, true, true, true)],
    ["Fansly, tips off", FS, false, set(false, false, false, false)],
    ["Fansly, tips on", FS, true, set(false, false, false, false)],
    ["mixed, tips off", MIXED, false, set(true, true, false, true)],
    ["mixed, tips on", MIXED, true, set(true, true, true, true)],
    ["unknown Platform", NONE, true, set(false, false, false, false)],
  ])("%s", (_label, platforms, tipsEnabled, want) => {
    expect(fanListChips({ platforms, tipsEnabled, pinnedFolderIds: [], active: ALL }).chips).toEqual(want);
  });
});

describe("fanListChips: the filter kept", () => {
  it.each<[string, Platform[], boolean, string[], ActiveChip, ActiveChip]>([
    ["All always kept (Fansly)", FS, false, [], ALL, ALL],
    ["Owe reply always kept (Fansly)", FS, false, [], b("owe-reply"), b("owe-reply")],
    ["Unread always kept (Fansly)", FS, false, [], b("unread"), b("unread")],
    ["All always kept (unknown)", NONE, false, [], ALL, ALL],
    ["Pinned kept (OnlyFans)", OF, false, [], b("pinned"), b("pinned")],
    ["Pinned hidden → All (Fansly)", FS, false, [], b("pinned"), ALL],
    ["Pinned hidden → All (unknown)", NONE, false, [], b("pinned"), ALL],
    ["With Tips kept (OnlyFans)", OF, false, [], b("who_tipped"), b("who_tipped")],
    ["With Tips hidden → All (Fansly)", FS, false, [], b("who_tipped"), ALL],
    ["Unread with tips kept (OnlyFans, tips on)", OF, true, [], b("unread_tips"), b("unread_tips")],
    ["Unread with tips → All (OnlyFans, tips off)", OF, false, [], b("unread_tips"), ALL],
    ["Unread with tips → All (Fansly, tips on)", FS, true, [], b("unread_tips"), ALL],
    ["Priority kept (OnlyFans)", OF, false, [], b("priority"), b("priority")],
    ["Priority hidden → All (Fansly)", FS, false, [], b("priority"), ALL],
    ["Priority kept (mixed)", MIXED, false, [], b("priority"), b("priority")],
    ["pinned folder kept (OnlyFans)", OF, false, ["7", "8"], folder("8"), folder("8")],
    ["unpinned folder → All (OnlyFans)", OF, false, ["7"], folder("8"), ALL],
    ["no folders loaded → All (OnlyFans)", OF, false, [], folder("8"), ALL],
    ["no folders read on Fansly → All", FS, false, [], folder("8"), ALL],
    ["pinned folder kept (mixed)", MIXED, false, ["8"], folder("8"), folder("8")],
  ])("%s", (_label, platforms, tipsEnabled, pinnedFolderIds, active, want) => {
    expect(fanListChips({ platforms, tipsEnabled, pinnedFolderIds, active }).active).toEqual(want);
  });

  it("a kept filter is the same object, so the write-back settles", () => {
    const active = folder("8");
    expect(fanListChips({ platforms: OF, tipsEnabled: false, pinnedFolderIds: ["8"], active }).active).toBe(active);
  });
});

describe("platformHonours: the Capability each list filter needs", () => {
  it.each<[ChatListFilter | null, string | null, boolean]>([
    [null, null, true], ["unread", null, true], ["pinned", null, false], ["priority", null, false],
    ["who_tipped", null, false], ["unread_tips", null, false], [null, "7", false], ["unread", "7", false],
  ])("filter %s, folder %s: OnlyFans yes, Fansly %s", (filter, listId, fansly) => {
    expect(platformHonours("onlyfans", filter, listId)).toBe(true);
    expect(platformHonours("fansly", filter, listId)).toBe(fansly);
  });
});
