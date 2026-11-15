/**
 * The Full AI config JSON modal's boxes (`FullAiSettings` ConfigJson), a reducer of their own beside the Test chat
 * reducer whose state they read (`fullAiTestChat.ts`).
 */

import type { TestChatState } from "@/components/automations/fullAiTestChat";

/** A config side as the JSON modal's box shows it. */
export const prettyJson = (v: unknown) => JSON.stringify(v, null, 2);

/** The JSON modal's boxes (`FullAiSettings` ConfigJson): each side's text as opened and as typed, and the rev they
 *  were read at. Both Store buttons write on `baseRev`, so a config stored elsewhere meanwhile (an assistant Apply,
 *  another tab) answers 409 (`stale`) instead of being overwritten; once the page adopts it (`jsonMoved`) Store is off. */
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
/** A box differs from what it opened with (Escape then stays off). */
export const jsonTyped = (ed: JsonEdit) => ed.text.checkpoint !== ed.opened.checkpoint || ed.text.draft !== ed.opened.draft;
/** The config moved since the boxes were read (adopted, or waiting as a Keep mine / Take theirs conflict). */
export const jsonMoved = (ed: JsonEdit, state: TestChatState) => (state.conflict?.rev ?? state.rev) !== ed.baseRev;
