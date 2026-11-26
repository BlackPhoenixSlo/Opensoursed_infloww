import type { Scope } from "@/contexts/ScopeContext";
import type { FanId } from "@/lib/fanId";
import type { Employee } from "@/lib/relayTypes";
import { groupOf, type SplitInboxConfig, type SplitInboxEdits } from "@/lib/splitInbox";

export const GROUP_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

export type Stored = ReadonlyMap<string, SplitInboxConfig>;

export interface SplitInboxForm {
  groupCount: number | null;
  chatterEdits: Record<string, number | null>;
  fanMoves: Record<string, number>;
}

export type Action =
  | { type: "count"; n: number }
  | { type: "moveFan"; fanId: string; group: number }
  | { type: "bindChatter"; chatterId: string; group: number | null };

export interface ScopeChatter {
  id: string;
  name: string;
  models: string[];
}

export const initialForm: SplitInboxForm = { groupCount: null, chatterEdits: {}, fanMoves: {} };

export function splitInboxFormReducer(state: SplitInboxForm, action: Action): SplitInboxForm {
  switch (action.type) {
    case "count":
      return { ...state, groupCount: action.n };
    case "moveFan":
      return { ...state, fanMoves: { ...state.fanMoves, [action.fanId]: action.group } };
    case "bindChatter":
      return { ...state, chatterEdits: { ...state.chatterEdits, [action.chatterId]: action.group } };
  }
}

export function scopeChatters(
  roster: readonly Pick<Employee, "chatter_id" | "display_name" | "kind" | "account_ids">[],
  accountIds: readonly string[],
): ScopeChatter[] {
  return roster.flatMap((e) => {
    if (e.kind === "owner") return [];
    const allowed = e.account_ids;
    const models = allowed == null ? [...accountIds] : accountIds.filter((aid) => allowed.includes(aid));
    return models.length > 0 ? [{ id: String(e.chatter_id), name: e.display_name, models }] : [];
  });
}

const countOf = (state: SplitInboxForm, cfg: SplitInboxConfig | undefined) => state.groupCount ?? cfg?.group_count ?? 1;

export function shownGroupCount(state: SplitInboxForm, stored: Stored): number | null {
  if (state.groupCount != null) return state.groupCount;
  const counts = new Set([...stored.values()].map((c) => c.group_count));
  return counts.size > 1 ? null : ([...counts][0] ?? 1);
}

export function widestGroupCount(state: SplitInboxForm, stored: Stored): number {
  return state.groupCount ?? Math.max(1, ...[...stored.values()].map((c) => c.group_count));
}

export function allowedGroups(state: SplitInboxForm, stored: Stored, chatter: ScopeChatter): readonly number[] {
  return GROUP_COUNTS.slice(0, Math.min(...chatter.models.map((id) => countOf(state, stored.get(id)))));
}

export function chatterGroupOf(state: SplitInboxForm, stored: Stored, chatter: ScopeChatter): number | null | "mixed" {
  const within = (g: number | null | undefined, n: number) => (g != null && g <= n ? g : null);
  if (Object.hasOwn(state.chatterEdits, chatter.id)) {
    return within(state.chatterEdits[chatter.id], allowedGroups(state, stored, chatter).length);
  }
  const seen = new Set(chatter.models.map((aid) => {
    const cfg = stored.get(aid);
    return within(cfg?.chatter_groups?.[chatter.id], countOf(state, cfg));
  }));
  return seen.size <= 1 ? ([...seen][0] ?? null) : "mixed";
}

export function fanGroupOf(state: SplitInboxForm, cfg: SplitInboxConfig, fanId: FanId): number {
  const n = countOf(state, cfg);
  const moved = state.fanMoves[String(fanId)];
  return moved != null && moved <= n ? moved : groupOf(fanId, { group_count: n, assignments: cfg.assignments });
}

export function buildEdits(state: SplitInboxForm, accountIds: readonly string[], scope: Scope["kind"]): SplitInboxEdits | null {
  const n = state.groupCount ?? Infinity;
  const edits: SplitInboxEdits = { account_ids: [...accountIds] };
  if (state.groupCount != null) edits.group_count = state.groupCount;
  const chatters = Object.entries(state.chatterEdits).map(([id, g]) => [id, g != null && g <= n ? g : null] as const);
  if (chatters.length) edits.chatter_groups = Object.fromEntries(chatters);
  const moves = Object.entries(state.fanMoves).filter(([, g]) => g <= n);
  if (scope === "model" && moves.length) edits.assignments = Object.fromEntries(moves);
  if (Object.keys(edits).length === 1) return null;
  return scope === "all" ? { ...edits, as_default: true } : edits;
}
