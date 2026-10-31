/**
 * ChatSurface's Fan insights drawer: open or not, and the two focus requests the header's "Notes" (spec F23) and
 * "Edit name" pencil (ticket 142) raise as they open it. Every Fan insights answers a raised count; both are 0
 * again once it closes, so the next open focuses nothing unless asked.
 */

export interface ChatDrawer {
  open: boolean;
  notesRequest: number;
  nicknameRequest: number;
}

export type ChatDrawerAction =
  | { type: "toggle" }
  | { type: "close" }
  /** Open on Notes. */
  | { type: "openNotes" }
  /** Open on Nickname. */
  | { type: "editName" };

const CLOSED: ChatDrawer = { open: false, notesRequest: 0, nicknameRequest: 0 };

export const initialChatDrawer = (open: boolean): ChatDrawer => ({ ...CLOSED, open });

export function chatDrawerReducer(state: ChatDrawer, action: ChatDrawerAction): ChatDrawer {
  switch (action.type) {
    case "toggle":
      return state.open ? CLOSED : { ...state, open: true };
    case "close":
      return state.open ? CLOSED : state;
    case "openNotes":
      return { ...state, open: true, notesRequest: state.notesRequest + 1 };
    case "editName":
      return { ...state, open: true, nicknameRequest: state.nicknameRequest + 1 };
  }
}
