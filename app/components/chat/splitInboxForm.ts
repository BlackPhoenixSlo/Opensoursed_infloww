import type { SplitInboxConfig } from "@/lib/splitInbox";

export interface SplitInboxForm {
  groupCount: number;
  assignments: Record<string, number>;
  chatterGroups: Record<string, number>;
}

export type Action =
  | { type: "count"; n: number }
  | { type: "moveFan"; fanId: string; group: number }
  | { type: "bindChatter"; chatterId: string; group: number | null };

export function initForm(stored: SplitInboxConfig): SplitInboxForm {
  return {
    groupCount: stored.group_count,
    assignments: stored.assignments,
    chatterGroups: stored.chatter_groups ?? {},
  };
}

export function splitInboxFormReducer(state: SplitInboxForm, action: Action): SplitInboxForm {
  switch (action.type) {
    case "count":
      return { ...state, groupCount: action.n };
    case "moveFan":
      return { ...state, assignments: { ...state.assignments, [action.fanId]: action.group } };
    case "bindChatter": {
      const rest = { ...state.chatterGroups };
      delete rest[action.chatterId];
      return { ...state, chatterGroups: action.group == null ? rest : { ...rest, [action.chatterId]: action.group } };
    }
  }
}

export function chatterGroupOf(state: SplitInboxForm, chatterId: string): number | null {
  const g = state.chatterGroups[chatterId];
  return g != null && g <= state.groupCount ? g : null;
}

export function buildPayload(state: SplitInboxForm): SplitInboxConfig {
  const within = (m: Record<string, number>) =>
    Object.fromEntries(Object.entries(m).filter(([, g]) => g <= state.groupCount));
  return {
    group_count: state.groupCount,
    assignments: within(state.assignments),
    chatter_groups: within(state.chatterGroups),
  };
}
