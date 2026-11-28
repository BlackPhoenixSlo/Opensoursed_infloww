import { describe, expect, it } from "vitest";

import type { OFChatItem } from "@/lib/relayTypes";
import {
  bundleChats, cellsReducer, cellToken, compareCellChats, greyAccounts, groupByCell, INITIAL_CELLS, mergeCellRows, spliceHead,
  tokenOf, type Action, type CellMap, type CellsState,
} from "./cellInbox";

const row = (account: string, fan: string, at?: string): OFChatItem =>
  ({ __accountId: account, withUser: { id: fan }, lastMessage: at ? { createdAt: at } : undefined }) as unknown as OFChatItem;
const keys = (rows: OFChatItem[]) => rows.map((c) => `${c.__accountId}:${c.withUser.id}`);
const run = (actions: Action[], from: CellsState = INITIAL_CELLS) => actions.reduce(cellsReducer, from);
const ask = (cell: string, accounts: string[], scope = "@u:1:1"): Action => ({ type: "ask", scope, cell, accounts });

const MAP: CellMap = {
  actor: "chatter:c1", grant_gen: 7, placement_gen: 3, cells: ["s03"],
  accounts: [
    { platform: "onlyfans", account_id: "20", cell: "s03" },
    { platform: "onlyfans", account_id: "10", cell: "s02" },
    { platform: "onlyfans", account_id: "11", cell: "s02" },
  ],
};

describe("compareCellChats", () => {
  it.each<[string, OFChatItem[], string[]]>([
    ["missing time first", [row("1", "5", "2026-11-26T10:00:00Z"), row("1", "6")], ["1:6", "1:5"]],
    ["newest first", [row("1", "5", "2026-11-26T09:00:00Z"), row("2", "6", "2026-11-26T10:00:00Z")], ["2:6", "1:5"]],
    ["time tie → account", [row("20", "1", "2026-11-26T10:00:00Z"), row("3", "1", "2026-11-26T10:00:00Z")], ["3:1", "20:1"]],
    ["time + account tie → fan", [row("3", "100", "2026-11-26T10:00:00Z"), row("3", "99", "2026-11-26T10:00:00Z")],
      ["3:99", "3:100"]],
    ["two missing times → account then fan", [row("2", "1"), row("1", "9"), row("1", "8")], ["1:8", "1:9", "2:1"]],
  ])("%s", (_n, rows, want) => {
    expect(keys([...rows].sort(compareCellChats))).toEqual(want);
    expect(keys([...rows].reverse().sort(compareCellChats))).toEqual(want);
  });
});

describe("mergeCellRows", () => {
  it.each<[string, OFChatItem[][], string[]]>([
    ["same fan on Creators in two Cells → two rows", [[row("10", "7", "2026-11-26T10:00:00Z")],
      [row("20", "7", "2026-11-26T10:00:00Z")]], ["10:7", "20:7"]],
    ["one account:fan twice across answers → one row, first kept", [[row("10", "7", "2026-11-26T10:00:00Z")],
      [row("10", "7", "2026-11-26T08:00:00Z"), row("20", "8", "2026-11-26T09:00:00Z")]], ["10:7", "20:8"]],
    ["empty answers", [[], []], []],
  ])("%s", (_n, lists, want) => {
    const out = mergeCellRows(lists);
    expect(keys(out)).toEqual(want);
    if (want[0] === "10:7" && lists[1].length === 2) expect(out[0].lastMessage?.createdAt).toBe("2026-11-26T10:00:00Z");
  });
});

describe("cellsReducer", () => {
  it.each<[string, Action[], string[]]>([
    ["asking greys nothing", [ask("s02", ["10", "11"]), ask("s03", ["20"])], []],
    ["answered ok greys nothing", [ask("s02", ["10"]), { type: "answered", scope: "@u:1:1", cell: "s02", partial: [] }], []],
    ["timed out greys only that Cell", [ask("s02", ["10", "11"]), ask("s03", ["20"]),
      { type: "timedOut", scope: "@u:1:1", cell: "s02" }, { type: "answered", scope: "@u:1:1", cell: "s03", partial: [] }],
      ["10", "11"]],
    ["failed greys that Cell", [ask("s03", ["20"]), { type: "failed", scope: "@u:1:1", cell: "s03" }], ["20"]],
    ["partial greys only named accounts", [ask("s02", ["10", "11"]),
      { type: "answered", scope: "@u:1:1", cell: "s02", partial: ["11"] }], ["11"]],
    ["re-ask keeps grey until it answers", [ask("s02", ["10"]), { type: "timedOut", scope: "@u:1:1", cell: "s02" },
      ask("s02", ["10"])], ["10"]],
    ["recovery clears grey", [ask("s02", ["10"]), { type: "failed", scope: "@u:1:1", cell: "s02" }, ask("s02", ["10"]),
      { type: "answered", scope: "@u:1:1", cell: "s02", partial: [] }], []],
    ["a new scope drops old Cells", [ask("s02", ["10"]), { type: "failed", scope: "@u:1:1", cell: "s02" },
      ask("s03", ["20"], "@u:2:1")], []],
    ["a stale scope's answer is ignored", [ask("s02", ["10"], "@u:2:1"),
      { type: "failed", scope: "@u:1:1", cell: "s02" }], []],
    ["an answer for a Cell never asked is ignored", [{ type: "failed", scope: "", cell: "s09" }], []],
  ])("%s", (_n, actions, want) => {
    expect([...greyAccounts(run(actions))].sort()).toEqual(want);
  });

  it("an ignored action keeps the same state object", () => {
    const s = run([ask("s02", ["10"])]);
    expect(cellsReducer(s, { type: "answered", scope: "@other", cell: "s02", partial: [] })).toBe(s);
  });
});

describe("plan", () => {
  it("groups granted accounts by Cell and drops ungranted ones", () => {
    expect(groupByCell(["20", "10", "11", "99"], MAP)).toEqual([["s02", ["10", "11"]], ["s03", ["20"]]]);
  });

  it("token carries actor, grant generation and Placement generation", () => {
    expect(cellToken(MAP)).toBe("@chatter:c1:7:3");
    expect(tokenOf("10,11,@chatter:c1:7:3")).toBe("@chatter:c1:7:3");
    expect(tokenOf("10,11")).toBe("");
    expect(cellToken({ ...MAP, grant_gen: 8 })).not.toBe(cellToken(MAP));
    expect(cellToken({ ...MAP, placement_gen: 4 })).not.toBe(cellToken(MAP));
  });
});

describe("bundleChats", () => {
  it("splits chats answers, refusals and partial", () => {
    const got = bundleChats({
      answers: [
        { accountId: null, read: "accounts", body: {} },
        { accountId: "10", read: "notificationCounts", body: {} },
        { accountId: "10", read: "chats", body: { list: [], hasMore: false } },
        { accountId: "11", read: "chats", status: 504, detail: { upstream_status: "bundle_deadline" } },
        { accountId: "12", read: "*", status: 404, detail: "Bundle does not include this Creator" },
        { accountId: "13", read: "chats", status: 404, detail: { error: "unknown_account", message: "Unknown account_id '13'" } },
        { accountId: "14", read: "chats", status: 404, detail: "Not Found" },
      ],
      partial: ["onlyfans:11", "onlyfans:12"],
    });
    expect(got).toEqual({ chats: [{ accountId: "10", body: { list: [], hasMore: false } }], failed: ["11", "12", "13", "14"],
      partial: ["11", "12"], gone: ["13"], unsupported: ["12"] });
  });

  it("a junk body is no rows, nothing failed", () => {
    expect(bundleChats(null)).toEqual({ chats: [], failed: [], partial: [], gone: [], unsupported: [] });
  });
});

describe("spliceHead", () => {
  const page0 = {
    rows: [row("10", "1", "2026-11-26T10:00:00Z"), row("20", "2", "2026-11-26T09:00:00Z"), row("20", "3", "2026-11-26T08:00:00Z")],
    hasMore: true, moreAccounts: ["10", "20"], scanned: 3, partial: true, missing: ["20"], askedSeq: 4,
  };
  it("replaces only the down Creators' rows, keeps the rest and the page stamps", () => {
    const head = { rows: [row("20", "9", "2026-11-26T11:00:00Z")], hasMore: false, moreAccounts: [], scanned: 1 };
    const out = spliceHead(page0, head, new Set(["20"]));
    expect(keys(out.rows)).toEqual(["20:9", "10:1"]);
    expect(out.moreAccounts).toEqual(["10"]);
    expect(out.hasMore).toBe(true);
    expect(out.partial).toBeUndefined();
    expect(out.missing).toBeUndefined();
    expect(out.askedSeq).toBe(4);
  });
  it("a still-failing Cell stays missing and keeps its last rows", () => {
    const head = { rows: [], hasMore: false, moreAccounts: [], scanned: 0, partial: true, missing: ["20"] };
    const out = spliceHead(page0, head, new Set(["20"]));
    expect(keys(out.rows)).toEqual(["10:1", "20:2", "20:3"]);
    expect(out.missing).toEqual(["20"]);
  });
});

it("keeps a missing Creator at its cursor while healthy Creators advance", async () => {
  const { nextCellCursors } = await import("./cellInbox");
  expect(nextCellCursors({
    rows: [], hasMore: true, moreAccounts: ["10", "20"], scanned: 1, missing: ["20"],
  }, 50, 10)).toEqual({ "10": 60, "20": 50 });
});
