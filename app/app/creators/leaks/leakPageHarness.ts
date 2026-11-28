import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Mock } from "vitest";
import { screen } from "@testing-library/react";

import { relay, RelayError } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;

export const setup = (over: Record<string, unknown> = {}) =>
  ({ key: "missing", masked: null, is_owner: true, can_write: true, brand: null, previews: true, ...over });
export const UNKNOWN = { seeded: false, paused: false, paused_since: null, last_checked_at: null, next_check_at: null, counts: null, this_week: null, next_refresh_at: null };
export const LOCAL = { platform: "onlyfans", username: "miavale", display_name: "Mia Vale", on: true, synced: true, reachable: true };
export const ROSTER = {
  rows: [{ account_id: "acc-a", name: "Creator A", ...LOCAL, ...UNKNOWN }],
  untracked: [{ account_id: "acc-b", name: "Creator B" }],
  stale: false,
  fetched_at: "2026-11-27T12:00:00+00:00",
};
export const MIA_SERVICE = {
  seeded: true, paused: false, paused_since: null, last_checked_at: "2026-11-27T04:05:00Z", next_check_at: "2026-11-28T04:00:00Z",
  counts: { cached: 1, came_back_30d: 1, found_on_first_scan: 3, gone: 0, listed: 1, live: 1, new_today: 1, not_checked: 1 },
};
export const ROWAN_SERVICE = {
  seeded: false, paused: true, paused_since: "2026-11-20T09:00:00Z", last_checked_at: null, next_check_at: "2026-11-28T04:00:00Z",
  counts: { cached: 0, came_back_30d: 0, found_on_first_scan: 0, gone: 0, listed: 0, live: 0, new_today: 0, not_checked: 0 },
};
export const MERGED = {
  ...ROSTER,
  rows: [
    { account_id: "acc-a", name: "Creator A", ...LOCAL, ...MIA_SERVICE },
    { account_id: "acc-c", name: "Creator C", ...LOCAL, username: "rowanash", ...ROWAN_SERVICE },
  ],
};
export const MIA = { username: "miavale", verified: true, display_name: "Mia Vale" };
export const untracked = (suggested: Record<string, unknown> = MIA) => ({ tracked: false, identity: null, suggested, synced: false });
export const tracked = (synced = true) => ({
  tracked: true, synced, suggested: null,
  identity: { platform: "onlyfans", ...MIA, aliases: [], instagram: null, x: null, on: true },
});
export const NO_LEAKS = { leaks: [], next_cursor: null, stale: false, fetched_at: null };
export const golden = (name: string) => JSON.parse(readFileSync(
  resolve(__dirname, "../../../../service/tests/fixtures/leak_tracker_v1", `${name}.json`), "utf8")).response;
export const ACCOUNT_OF: Record<string, string> = { w_miavale_0001: "acc-a", w_rowanash_0002: "acc-c" };
export const asAll = (name: string) => {
  const { leaks, next_cursor } = golden(name);
  return {
    leaks: leaks.map(({ watch_id, ...l }: { watch_id: string }) => ({ ...l, account_id: ACCOUNT_OF[watch_id] })),
    next_cursor, stale: false, fetched_at: "2026-11-27T12:00:00+00:00",
  };
};
export const CREATOR_LEAKS = golden("creator_leaks").leaks;
export const CURSOR = golden("leaks").next_cursor as string;
export const drill = (leaks: unknown[], next_cursor: string | null = null, stale = false) =>
  ({ ...tracked(), leaks, next_cursor, stale, fetched_at: "2026-11-27T12:00:00+00:00" });
export type Answer = unknown | (() => unknown);
export const serve = (s: Record<string, unknown>, routes: Record<string, Answer> = {}) =>
  relayGet.mockImplementation(async (path: string) => {
    const all: Record<string, Answer> = {
      "/admin/leaks/setup": s, "/admin/leaks/roster": ROSTER, "/admin/leaks/all": NO_LEAKS,
      "/admin/leaks/watches/acc-a": tracked(), "/admin/leaks/watches/acc-b": untracked(), ...routes,
    };
    if (!(path in all)) throw new RelayError(404, "Not Found");
    const v = all[path];
    return typeof v === "function" ? (v as () => unknown)() : v;
  });
export const row = (name: string) => screen.getAllByTestId("of-creator-row").find((r) => r.textContent?.includes(name));
