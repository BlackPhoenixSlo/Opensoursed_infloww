import type { Employee } from "@/lib/relayTypes";
import type { SplitInboxConfig } from "@/lib/splitInbox";
import { buildPayload } from "./splitInboxForm";

export const GROUP_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

export interface SplitInboxAllForm {
  groupCount: number | null;
  chatterGroups: Record<string, number | null>;
}

export type AllAction =
  | { type: "count"; n: number }
  | { type: "bindChatter"; chatterId: string; group: number | null };

export interface ScopeChatter {
  id: string;
  name: string;
  models: string[];
}

export function scopeChatters(
  roster: readonly Pick<Employee, "chatter_id" | "display_name" | "kind" | "account_ids">[],
  accountIds: readonly string[],
): ScopeChatter[] {
  return roster.flatMap((e) => {
    if (e.kind === "owner") return [];
    const models = e.account_ids == null ? [...accountIds] : accountIds.filter((aid) => e.account_ids!.includes(aid));
    return models.length > 0 ? [{ id: String(e.chatter_id), name: e.display_name, models }] : [];
  });
}

export const initialAllForm: SplitInboxAllForm = { groupCount: null, chatterGroups: {} };

export function splitInboxAllFormReducer(state: SplitInboxAllForm, action: AllAction): SplitInboxAllForm {
  switch (action.type) {
    case "count":
      return { ...state, groupCount: action.n };
    case "bindChatter":
      return { ...state, chatterGroups: { ...state.chatterGroups, [action.chatterId]: action.group } };
  }
}

export function allChatterGroupOf(
  state: SplitInboxAllForm,
  stored: ReadonlyMap<string, SplitInboxConfig>,
  chatter: ScopeChatter,
): number | null | "mixed" {
  const within = (g: number | null | undefined) => (g != null && (state.groupCount == null || g <= state.groupCount) ? g : null);
  if (Object.hasOwn(state.chatterGroups, chatter.id)) return within(state.chatterGroups[chatter.id]);
  const seen = new Set(chatter.models.map((aid) => within(stored.get(aid)?.chatter_groups?.[chatter.id])));
  return seen.size <= 1 ? ([...seen][0] ?? null) : "mixed";
}

export function allowedGroups(
  state: SplitInboxAllForm,
  stored: ReadonlyMap<string, SplitInboxConfig>,
  chatter: ScopeChatter,
) {
  const count = state.groupCount ?? Math.min(...chatter.models.map((id) => stored.get(id)?.group_count ?? 1));
  return GROUP_COUNTS.slice(0, count);
}

export function selectedGroupCount(
  state: SplitInboxAllForm,
  stored: ReadonlyMap<string, SplitInboxConfig>,
): number | null {
  if (state.groupCount != null) return state.groupCount;
  const counts = new Set([...stored.values()].map((c) => c.group_count));
  return counts.size > 1 ? null : ([...counts][0] ?? 1);
}

export function shownGroupCount(
  state: SplitInboxAllForm,
  stored: ReadonlyMap<string, SplitInboxConfig>,
): number {
  return state.groupCount ?? Math.max(1, ...[...stored.values()].map((cfg) => cfg.group_count));
}

function sameGroups(a: Record<string, number> = {}, b: Record<string, number> = {}): boolean {
  const entries = Object.entries(a);
  return entries.length === Object.keys(b).length && entries.every(([id, group]) => b[id] === group);
}

export function buildPayloads(
  state: SplitInboxAllForm,
  stored: ReadonlyMap<string, SplitInboxConfig>,
  chatters: readonly ScopeChatter[],
): Map<string, SplitInboxConfig> {
  const sees = new Map(chatters.map((c) => [c.id, c.models]));
  const payloads = new Map<string, SplitInboxConfig>();
  for (const [aid, cfg] of stored) {
    const chatterGroups = { ...cfg.chatter_groups };
    for (const [cid, g] of Object.entries(state.chatterGroups)) {
      if (!sees.get(cid)?.includes(aid)) continue;
      if (g == null) delete chatterGroups[cid];
      else chatterGroups[cid] = g;
    }
    const payload = buildPayload({ groupCount: state.groupCount ?? cfg.group_count, assignments: cfg.assignments, chatterGroups });
    if (payload.group_count !== cfg.group_count ||
        !sameGroups(payload.assignments, cfg.assignments) ||
        !sameGroups(payload.chatter_groups, cfg.chatter_groups)) {
      payloads.set(aid, payload);
    }
  }
  return payloads;
}
