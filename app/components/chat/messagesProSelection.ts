import type { FanListSelection } from "@/components/chat/FanList";

export interface MessagesProSelection {
  selected: FanListSelection | null;
  fromLink: boolean;
}

export type MessagesProSelectionAction =
  | { type: "select"; sel: FanListSelection }
  | { type: "clear" };

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
