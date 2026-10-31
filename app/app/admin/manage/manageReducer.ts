/**
 * /admin/manage's list state as a pure reducer — the user rows, the key-status
 * roster that draws their badges, the live-only filter and the one open pane.
 *
 *   • A refresh makes two calls that fail INDEPENDENTLY; both land in one
 *     `refreshSettled` and each outcome is applied on its own.
 *     /admin/users is the page: grant, revoke, delete and impersonate all hang
 *     off it. Its failure keeps the last rows (none on a failed FIRST load —
 *     the page then shows the error, never "No users registered yet.") and
 *     sets `error`. The key roster only draws badges (both reads are
 *     master-only): its failure must not take the page down, but must not be
 *     silent either — it drops the map (last load's "needs a key" must not
 *     sit next to a key that may have changed) and adds a line to `error`. A roster that loads
 *     replaces the map even when /admin/users failed.
 *   • `keyStatus` null = the roster did not load; `{}` = it loaded EMPTY. It
 *     used to be "failed" iff `keys(keyStatus).length === 0`, so a roster that
 *     loaded empty read as failed and the live-only filter quietly stopped
 *     filtering.
 *   • The live-only filter only filters on a loaded roster (`visibleRows`) —
 *     a failed key-status call must not empty a list /admin/users returned.
 *     On a missing roster the filter says it is off (`filterNote`), keyed on
 *     `keyStatus` alone: `error` is cleared by the next refreshStart and may
 *     be the users call's.
 *   • Refreshes overlap (the button, and each pane's save). Each carries a
 *     `seq`; only the latest one's answer lands and clears `refreshing` — an
 *     older answer landing last would restore deleted rows or clear a newer
 *     error.
 *   • At most one pane is open; toggling the open one closes it. A pane whose
 *     row leaves `visibleRows` (deleted, or hidden by live-only) closes, so it
 *     cannot reappear later with its form's input gone.
 */

import type { AgencyKeyFacts } from "@/components/setup/AgencyKeyBadges";
import { errText } from "@/lib/errText";

export interface AdminUserRow {
  id: string;
  username: string;
  created_at: string;
  last_seen_at: string;
  account_count: number;
}

/** One row of GET /admin/users/llm-key-status — provider NAMES only, never a
 *  value or a hint. The per-agency pane is where a masked hint belongs. */
export interface AgencyKeyStatus extends AgencyKeyFacts {
  user_id: string;
  username: string;
}

export type Pane = "grant" | "keys" | "delete" | "impersonate";
export type OpenPane = { userId: string; pane: Pane } | null;

export interface ManageState {
  /** null = no /admin/users answer has landed (loading, or the first load failed). */
  rows: AdminUserRow[] | null;
  /** null = the roster did not load (not yet, or the call failed). */
  keyStatus: Record<string, AgencyKeyStatus> | null;
  liveOnly: boolean;
  error: string | null;
  open: OpenPane;
  refreshing: boolean;
  /** The latest refresh's id; a settle carrying another one is stale. */
  seq: number;
}

export type ManageAction =
  | { type: "refreshStart"; seq: number }
  | {
      type: "refreshSettled";
      seq: number;
      users: PromiseSettledResult<AdminUserRow[]>;
      roster: PromiseSettledResult<{ agencies: AgencyKeyStatus[] }>;
    }
  | { type: "liveOnly"; on: boolean }
  | { type: "togglePane"; userId: string; pane: Pane }
  | { type: "closePane" };

// OFF by default, unlike the Setup keys card: this is the screen where a
// founder grants a brand-new agency its FIRST model, and such an agency has
// zero live models by definition — defaulting the filter ON would hide exactly
// the row you came to act on. `refreshing` starts true: the page fires its
// first load on mount, and rows===null && !refreshing means that load FAILED.
export const initialManageState: ManageState = {
  rows: null, keyStatus: null, liveOnly: false,
  error: null, open: null, refreshing: true, seq: 0,
};

/** The rows on screen: all of them, or — live-only, on a loaded roster — those
 *  with a live model session. */
export function visibleRows(s: Pick<ManageState, "rows" | "keyStatus" | "liveOnly">): AdminUserRow[] {
  const rows = s.rows ?? [];
  const ks = s.keyStatus;
  if (!s.liveOnly || ks === null) return rows;
  return rows.filter((u) => (ks[u.id]?.live_accounts ?? 0) > 0);
}

/** The live-only filter's count, or — no roster — that it is not filtering. */
export function filterNote(s: Pick<ManageState, "rows" | "keyStatus" | "liveOnly">): string {
  if (s.keyStatus === null) return "(key status unavailable — filter off)";
  return `(${visibleRows(s).length} of ${(s.rows ?? []).length})`;
}

/** DeleteForm's submit gate: the typed word, a password, and not already sending. */
export function canDelete(f: { confirm: string; adminPassword: string; busy: boolean }): boolean {
  return f.confirm === "delete" && f.adminPassword.length > 0 && !f.busy;
}

/** Close the open pane when its row is no longer on screen. */
function closeHidden(s: ManageState): ManageState {
  const open = s.open;
  if (open === null || visibleRows(s).some((u) => u.id === open.userId)) return s;
  return { ...s, open: null };
}

export function manageReducer(state: ManageState, action: ManageAction): ManageState {
  switch (action.type) {
    case "refreshStart":
      return { ...state, seq: action.seq, error: null, refreshing: true };
    case "refreshSettled": {
      if (action.seq !== state.seq) return state;
      const { users, roster } = action;
      const errors: string[] = [];
      if (users.status === "rejected") errors.push(errText(users.reason));
      if (roster.status === "rejected") errors.push(`Key status unavailable — ${errText(roster.reason)}`);
      return closeHidden({
        ...state,
        refreshing: false,
        rows: users.status === "fulfilled" ? users.value : state.rows,
        keyStatus: roster.status === "fulfilled"
          ? Object.fromEntries(roster.value.agencies.map((a) => [a.user_id, a]))
          : null,
        error: errors.length ? errors.join(" · ") : null,
      });
    }
    case "liveOnly":
      return closeHidden({ ...state, liveOnly: action.on });
    case "togglePane": {
      const cur = state.open;
      const same = cur !== null && cur.userId === action.userId && cur.pane === action.pane;
      return { ...state, open: same ? null : { userId: action.userId, pane: action.pane } };
    }
    case "closePane":
      return { ...state, open: null };
  }
}
