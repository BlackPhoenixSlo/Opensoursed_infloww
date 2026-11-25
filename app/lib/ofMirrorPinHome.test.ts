import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { PIN_EMPTY_ALL, pinHomeHref, pinHomeRows, pinHomeStatus, type PinList } from "./ofMirrorPinHome";
import type { FolderOrder, FolderSort, FolderSortKey } from "./ofMirrorDataLists";

const fixture = <T = unknown>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/${name}.json`), "utf8"));

const LISTS: PinList[] = [
  { id: 20, name: "Bravo", usersCount: 1, postsCount: 40 },
  { id: 30, name: "Alpha", usersCount: 5, postsCount: 0 },
  { id: 10, name: "Charlie", usersCount: 3, postsCount: 2 },
  { id: 40, name: "Delta", usersCount: 0, canPinnedToFeed: false },
];

describe("pinHomeRows: OF's can_pin lists (canPinnedToFeed not false) in the dialog's sort", () => {
  it.each<[FolderSortKey, FolderOrder, string[]]>([
    ["custom", "desc", ["Bravo", "Alpha", "Charlie"]],
    ["recent", "desc", ["Alpha", "Bravo", "Charlie"]],
    ["recent", "asc", ["Charlie", "Bravo", "Alpha"]],
    ["name", "desc", ["Charlie", "Bravo", "Alpha"]],
    ["name", "asc", ["Alpha", "Bravo", "Charlie"]],
    ["people", "desc", ["Alpha", "Charlie", "Bravo"]],
    ["people", "asc", ["Bravo", "Charlie", "Alpha"]],
  ])("%s %s", (sort, order, want) => expect(pinHomeRows(LISTS, { sort, order })!.map((l) => l.name)).toEqual(want));
  it("each sort option orders the rows differently", () => {
    const orders = (["custom", "recent", "name", "people"] as const).map((sort) => pinHomeRows(LISTS, { sort, order: "desc" })!.map((l) => l.id).join());
    expect(new Set(orders).size).toBe(4);
  });
  it("no answer yet: no rows", () => expect(pinHomeRows(undefined, { sort: "name", order: "asc" })).toBeUndefined());
  it("OF's own fixture: every list it marks pinnable", () => {
    const list = fixture<{ list: PinList[] }>("messages-lists").list;
    expect(pinHomeRows(list, { sort: "custom", order: "desc" })!.length).toBe(list.filter((l) => l.canPinnedToFeed !== false).length);
  });
});

describe("pinHomeHref: the dialog in a sort is its page's ?fsort=&forder= (default Custom, Descending adds nothing)", () => {
  it.each<[FolderSort, string]>([
    [{ sort: "custom", order: "desc" }, "/of-manager/home/state-feed-tabs-edit"],
    [{ sort: "name", order: "asc" }, "/of-manager/home/state-feed-tabs-edit?fsort=name&forder=asc"],
    [{ sort: "recent", order: "desc" }, "/of-manager/home/state-feed-tabs-edit?fsort=recent&forder=desc"],
  ])("%j", (sorted, want) => expect(pinHomeHref(sorted)).toBe(want));
});

describe("pinHomeStatus: the line under the rows (null: hidden)", () => {
  it.each<[Parameters<typeof pinHomeStatus>[0], string | null]>([
    [{ scoped: false, rows: undefined, error: null }, PIN_EMPTY_ALL],
    [{ scoped: true, rows: undefined, error: null }, "Loading…"],
    [{ scoped: true, rows: undefined, error: "502 Bad Gateway" }, "Could not load: 502 Bad Gateway"],
    [{ scoped: true, rows: [], error: null }, "Nothing found"],
    [{ scoped: true, rows: LISTS, error: null }, null],
  ])("%j", (s, want) => expect(pinHomeStatus(s)).toBe(want));
});
