/**
 * Messages Pro's open Thread: the selected Fan, and `fromLink`, true while the Deep link's first selection stands
 * (its Thread is built from the link and starts with Fan insights closed). Any later selection, or none, ends
 * it, so the arrival never outlives the selection it came with.
 */

import type { FanListSelection } from "@/components/chat/FanList";

export interface MessagesProSelection {
  selected: FanListSelection | null;
  fromLink: boolean;
}

export type MessagesProSelectionAction =
  /** A Fan picked in the app (Fan List, Fan tab, notification). */
  | { type: "select"; sel: FanListSelection }
  /** Thread emptied: Back, ✕ on the last Fan tab, or a scope that no longer covers it. */
  | { type: "clear" };

/** `linked`: the Deep link's Fan, selected on arrival; null without a Deep link. */
export const initialMessagesProSelection = (linked: FanListSelection | null): MessagesProSelection =>
  ({ selected: linked, fromLink: linked !== null });

export function messagesProSelectionReducer(
  state: MessagesProSelection, action: MessagesProSelectionAction,
): MessagesProSelection {
  switch (action.type) {
    case "select":
      return { selected: action.sel, fromLink: false };
    case "clear":
      return state.selected === null && !state.fromLink ? state : { selected: null, fromLink: false };
  }
}
