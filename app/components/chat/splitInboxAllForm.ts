import type { Employee } from "@/lib/relayTypes";
import type { SplitInboxConfig } from "@/lib/splitInbox";
import { buildPayload } from "./splitInboxForm";

export interface SplitInboxAllForm {
  groupCount: number;
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

export function initAllForm(stored: ReadonlyMap<string, SplitInboxConfig>): SplitInboxAllForm {
  return { groupCount: Math.max(1, ...[...stored.values()].map((c) => c.group_count)), chatterGroups: {} };
}

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
  const within = (g: number | null | undefined) => (g != null && g <= state.groupCount ? g : null);
  if (Object.hasOwn(state.chatterGroups, chatter.id)) return within(state.chatterGroups[chatter.id]);
  const seen = new Set(chatter.models.map((aid) => within(stored.get(aid)?.chatter_groups?.[chatter.id])));
  return seen.size <= 1 ? ([...seen][0] ?? null) : "mixed";
}

export function buildPayloads(
  state: SplitInboxAllForm,
  stored: ReadonlyMap<string, SplitInboxConfig>,
  chatters: readonly ScopeChatter[],
): Map<string, SplitInboxConfig> {
  const sees = new Map(chatters.map((c) => [c.id, c.models]));
  return new Map([...stored].map(([aid, cfg]) => {
    const chatterGroups = { ...cfg.chatter_groups };
    for (const [cid, g] of Object.entries(state.chatterGroups)) {
      if (!sees.get(cid)?.includes(aid)) continue;
      if (g == null) delete chatterGroups[cid];
      else chatterGroups[cid] = g;
    }
    return [aid, buildPayload({ groupCount: state.groupCount, assignments: cfg.assignments, chatterGroups })];
  }));
}
