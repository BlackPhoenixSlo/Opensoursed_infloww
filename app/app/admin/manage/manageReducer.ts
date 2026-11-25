import type { AgencyKeyFacts } from "@/components/setup/AgencyKeyBadges";
import { errText } from "@/lib/errText";

export interface AdminUserRow {
  id: string;
  username: string;
  created_at: string;
  last_seen_at: string;
  account_count: number;
}

export interface AgencyKeyStatus extends AgencyKeyFacts {
  user_id: string;
  username: string;
}

export type Pane = "grant" | "keys" | "delete" | "impersonate";
export type OpenPane = { userId: string; pane: Pane } | null;

export interface ManageState {
  rows: AdminUserRow[] | null;
  // null = roster did not load; {} = loaded empty (not the same)
  keyStatus: Record<string, AgencyKeyStatus> | null;
  liveOnly: boolean;
  error: string | null;
  open: OpenPane;
  refreshing: boolean;
  // only the latest refresh's answer lands; an older one would restore deleted rows
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

// liveOnly OFF: a new agency has zero live models, ON would hide the row to act on; refreshing starts true so rows===null && !refreshing = first load failed
export const initialManageState: ManageState = {
  rows: null, keyStatus: null, liveOnly: false,
  error: null, open: null, refreshing: true, seq: 0,
};

export function visibleRows(s: Pick<ManageState, "rows" | "keyStatus" | "liveOnly">): AdminUserRow[] {
  const rows = s.rows ?? [];
  const ks = s.keyStatus;
  if (!s.liveOnly || ks === null) return rows;
  return rows.filter((u) => (ks[u.id]?.live_accounts ?? 0) > 0);
}

export function filterNote(s: Pick<ManageState, "rows" | "keyStatus" | "liveOnly">): string {
  if (s.keyStatus === null) return "(key status unavailable — filter off)";
  return `(${visibleRows(s).length} of ${(s.rows ?? []).length})`;
}

export function canDelete(f: { confirm: string; adminPassword: string; busy: boolean }): boolean {
  return f.confirm === "delete" && f.adminPassword.length > 0 && !f.busy;
}

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
