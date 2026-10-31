import { describe, expect, it } from "vitest";

import {
  canDelete, filterNote, initialManageState, manageReducer, visibleRows,
  type AdminUserRow, type AgencyKeyStatus, type ManageAction, type ManageState,
} from "./manageReducer";

const row = (id: string): AdminUserRow => ({
  id, username: `u${id}`, created_at: "2026-01-01T00:00:00Z", last_seen_at: "2026-01-01T00:00:00Z", account_count: 1,
});
const status = (user_id: string, live_accounts: number): AgencyKeyStatus => ({
  user_id, username: `u${user_id}`, accounts: 1, live_accounts, blocked_accounts: 0,
  providers_set: [], missing_providers: [],
});
const ROWS = [row("1"), row("2"), row("3")];
type Users = PromiseSettledResult<AdminUserRow[]>;
type Roster = PromiseSettledResult<{ agencies: AgencyKeyStatus[] }>;
const ok = <T,>(value: T): PromiseFulfilledResult<T> => ({ status: "fulfilled", value });
const no = (reason: unknown): PromiseRejectedResult => ({ status: "rejected", reason });

const run = (actions: ManageAction[], from: ManageState = initialManageState) => actions.reduce(manageReducer, from);
const start = (seq: number): ManageAction => ({ type: "refreshStart", seq });
const settle = (seq: number, users: Users, roster: Roster): ManageAction => ({ type: "refreshSettled", seq, users, roster });
/** One whole refresh, numbered after `from`'s. */
const refreshed = (users: Users, roster: Roster, from: ManageState = initialManageState) =>
  run([start(from.seq + 1), settle(from.seq + 1, users, roster)], from);
const ids = (s: ManageState) => (s.keyStatus === null ? null : Object.keys(s.keyStatus));

describe("refreshSettled — each call's outcome applied on its own", () => {
  it.each<[string, Users, Roster, { rows: AdminUserRow[] | null; ids: string[] | null; error: string | null }]>([
    ["both load", ok(ROWS), ok({ agencies: [status("1", 2)] }),
      { rows: ROWS, ids: ["1"], error: null }],
    ["roster loads EMPTY — loaded, not failed", ok(ROWS), ok({ agencies: [] }),
      { rows: ROWS, ids: [], error: null }],
    ["roster fails (Error)", ok(ROWS), no(new Error("403")),
      { rows: ROWS, ids: null, error: "Key status unavailable — 403" }],
    ["roster fails (non-Error)", ok(ROWS), no("nope"),
      { rows: ROWS, ids: null, error: "Key status unavailable — nope" }],
    ["first users load fails, roster loads — no rows, the new map, the error", no(new Error("502")),
      ok({ agencies: [status("1", 2)] }), { rows: null, ids: ["1"], error: "502" }],
    ["both fail on the first load (non-Error users)", no("down"), no(new Error("x")),
      { rows: null, ids: null, error: "down · Key status unavailable — x" }],
  ])("%s", (_name, users, roster, want) => {
    const s = refreshed(users, roster);
    expect(s.rows).toEqual(want.rows);
    expect(ids(s)).toEqual(want.ids);
    expect(s.error).toBe(want.error);
    expect(s.refreshing).toBe(false);
  });

  const good = refreshed(ok(ROWS), ok({ agencies: [status("1", 2)] }));
  it.each<[string, Users, Roster, { ids: string[] | null; error: string }]>([
    ["users fail, roster loads — last rows kept, the NEW map taken", no(new Error("502")),
      ok({ agencies: [status("2", 1)] }), { ids: ["2"], error: "502" }],
    ["both fail — last rows kept, the stale map dropped", no(new Error("502")), no(new Error("403")),
      { ids: null, error: "502 · Key status unavailable — 403" }],
  ])("after a good load: %s", (_name, users, roster, want) => {
    const s = refreshed(users, roster, good);
    expect(s.rows).toBe(good.rows);
    expect(ids(s)).toEqual(want.ids);
    expect(s.error).toBe(want.error);
    expect(s.refreshing).toBe(false);
  });

  it("after a good load: a failed roster drops the stale map", () => {
    expect(refreshed(ok(ROWS), no(new Error("403")), good).keyStatus).toBeNull();
  });

  it("the first load is pending from the start (a failed one is rows null + not refreshing)", () => {
    expect(initialManageState.rows).toBeNull();
    expect(initialManageState.refreshing).toBe(true);
    const failed = refreshed(no(new Error("502")), no(new Error("403")));
    expect([failed.rows, failed.refreshing]).toEqual([null, false]);
  });

  it("refreshStart clears the error, sets refreshing and takes the seq", () => {
    const failed = refreshed(no(new Error("502")), ok({ agencies: [] }));
    const s = run([start(7)], failed);
    expect([s.error, s.refreshing, s.seq]).toEqual([null, true, 7]);
  });
});

describe("overlapping refreshes — only the latest lands", () => {
  const good = refreshed(ok(ROWS), ok({ agencies: [status("1", 2)] }));
  const afterDelete = ROWS.slice(1);

  it("an older answer landing LAST is ignored: no deleted row back, newer error kept", () => {
    const s = run([
      start(good.seq + 1), start(good.seq + 2),
      settle(good.seq + 2, ok(afterDelete), no(new Error("403"))),
      settle(good.seq + 1, ok(ROWS), ok({ agencies: [status("1", 2)] })),
    ], good);
    expect(s.rows).toBe(afterDelete);
    expect(s.keyStatus).toBeNull();
    expect(s.error).toBe("Key status unavailable — 403");
    expect(s.refreshing).toBe(false);
  });

  it("an older answer landing FIRST does not end the newer refresh", () => {
    const s = run([
      start(good.seq + 1), start(good.seq + 2),
      settle(good.seq + 1, ok(afterDelete), ok({ agencies: [] })),
    ], good);
    expect(s.refreshing).toBe(true);
    expect(s.rows).toBe(good.rows);
  });
});

describe("visibleRows and the filter note", () => {
  const roster = ok({ agencies: [status("1", 2), status("2", 0)] });
  const on = (s: ManageState) => run([{ type: "liveOnly", on: true }], s);
  const failedRoster = refreshed(ok(ROWS), no(new Error("403")));
  it.each<[string, ManageState, string[], string]>([
    ["filter off shows all", refreshed(ok(ROWS), roster), ["1", "2", "3"], "(3 of 3)"],
    ["live-only keeps live agencies", on(refreshed(ok(ROWS), roster)), ["1"], "(1 of 3)"],
    ["live-only on an EMPTY loaded roster hides everyone (nobody is live)",
      on(refreshed(ok(ROWS), ok({ agencies: [] }))), [], "(0 of 3)"],
    ["live-only on a FAILED roster does not filter, and says so",
      on(failedRoster), ["1", "2", "3"], "(key status unavailable — filter off)"],
    ["a FAILED roster says the filter is off with the box unchecked too",
      failedRoster, ["1", "2", "3"], "(key status unavailable — filter off)"],
    ["a refresh started on a FAILED roster keeps the note (error cleared, map still null)",
      run([start(failedRoster.seq + 1)], on(failedRoster)), ["1", "2", "3"], "(key status unavailable — filter off)"],
    ["a users-only failure on a failed roster keeps the note", on(refreshed(no(new Error("502")),
      no(new Error("403")), failedRoster)), ["1", "2", "3"], "(key status unavailable — filter off)"],
    ["before the first load", on(initialManageState), [], "(key status unavailable — filter off)"],
  ])("%s", (_name, s, want, note) => {
    expect(visibleRows(s).map((u) => u.id)).toEqual(want);
    expect(filterNote(s)).toBe(note);
  });
});

describe("panes", () => {
  it.each<[string, ManageAction[], ManageState["open"]]>([
    ["open one", [{ type: "togglePane", userId: "1", pane: "grant" }], { userId: "1", pane: "grant" }],
    ["toggle the open one closes it",
      [{ type: "togglePane", userId: "1", pane: "grant" }, { type: "togglePane", userId: "1", pane: "grant" }], null],
    ["another pane on the same user replaces it",
      [{ type: "togglePane", userId: "1", pane: "grant" }, { type: "togglePane", userId: "1", pane: "delete" }],
      { userId: "1", pane: "delete" }],
    ["another user's pane replaces it",
      [{ type: "togglePane", userId: "1", pane: "keys" }, { type: "togglePane", userId: "2", pane: "keys" }],
      { userId: "2", pane: "keys" }],
    ["closePane", [{ type: "togglePane", userId: "1", pane: "impersonate" }, { type: "closePane" }], null],
  ])("%s", (_name, actions, open) => {
    expect(run(actions).open).toEqual(open);
  });

  // The open pane follows its row: gone from visibleRows → closed.
  const roster = ok({ agencies: [status("1", 2), status("2", 0)] });
  const loaded = refreshed(ok(ROWS), roster);
  const openOn = (userId: string, s: ManageState = loaded) => run([{ type: "togglePane", userId, pane: "grant" }], s);
  it.each<[string, ManageState, ManageState["open"]]>([
    ["live-only hides the open row → closed", run([{ type: "liveOnly", on: true }], openOn("2")), null],
    ["live-only keeps a live open row → stays", run([{ type: "liveOnly", on: true }], openOn("1")),
      { userId: "1", pane: "grant" }],
    ["a refresh without the open row (deleted) → closed", refreshed(ok(ROWS.slice(1)), roster, openOn("1")), null],
    ["a refresh whose users call failed keeps it", refreshed(no(new Error("502")), roster, openOn("3")),
      { userId: "3", pane: "grant" }],
    ["live-only + the roster fails: filter off, so it stays",
      refreshed(ok(ROWS), no(new Error("403")), run([{ type: "liveOnly", on: true }], openOn("1"))),
      { userId: "1", pane: "grant" }],
    ["a refresh's roster turns the open row non-live under live-only → closed",
      refreshed(ok(ROWS), ok({ agencies: [status("1", 0)] }), run([{ type: "liveOnly", on: true }], openOn("1"))),
      null],
  ])("%s", (_name, s, open) => {
    expect(s.open).toEqual(open);
  });
});

describe("canDelete", () => {
  it.each<[string, { confirm: string; adminPassword: string; busy: boolean }, boolean]>([
    ["all set", { confirm: "delete", adminPassword: "pw", busy: false }, true],
    ["word not typed", { confirm: "", adminPassword: "pw", busy: false }, false],
    ["wrong word", { confirm: "Delete", adminPassword: "pw", busy: false }, false],
    ["no password", { confirm: "delete", adminPassword: "", busy: false }, false],
    ["already deleting", { confirm: "delete", adminPassword: "pw", busy: true }, false],
  ])("%s", (_name, f, want) => {
    expect(canDelete(f)).toBe(want);
  });
});
