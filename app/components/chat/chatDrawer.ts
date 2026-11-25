export interface ChatDrawer {
  open: boolean;
  notesRequest: number;
  nicknameRequest: number;
}

export type ChatDrawerAction =
  | { type: "toggle" }
  | { type: "close" }
  | { type: "openNotes" }
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
