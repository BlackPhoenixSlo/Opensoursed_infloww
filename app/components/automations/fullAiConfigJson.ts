import type { TestChatState } from "@/components/automations/fullAiTestChat";

export const prettyJson = (v: unknown) => JSON.stringify(v, null, 2);

// Both Store buttons write on baseRev: a config stored elsewhere meanwhile answers 409 instead of being overwritten.
export type JsonSide = "checkpoint" | "draft";
export interface JsonEdit { baseRev: number; opened: Record<JsonSide, string>; text: Record<JsonSide, string> }
export type JsonEditAction = { type: "type"; side: JsonSide; text: string };
export function jsonEditInit(state: TestChatState): JsonEdit {
  const opened = { checkpoint: prettyJson(state.checkpoint ?? {}), draft: prettyJson(state.draft ?? {}) };
  return { baseRev: state.rev, opened, text: opened };
}
export function jsonEditReducer(ed: JsonEdit, action: JsonEditAction): JsonEdit {
  return { ...ed, text: { ...ed.text, [action.side]: action.text } };
}
export const jsonTyped = (ed: JsonEdit) => ed.text.checkpoint !== ed.opened.checkpoint || ed.text.draft !== ed.opened.draft;
export const jsonMoved = (ed: JsonEdit, state: TestChatState) => (state.conflict?.rev ?? state.rev) !== ed.baseRev;
