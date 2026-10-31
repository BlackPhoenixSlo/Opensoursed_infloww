import { describe, expect, it } from "vitest";

import type { FanListSelection } from "@/components/chat/FanList";
import {
  initialMessagesProSelection, messagesProSelectionReducer, type MessagesProSelection, type MessagesProSelectionAction,
} from "@/components/chat/messagesProSelection";
import type { OFChatItem } from "@/lib/relay";

const sel = (fanId: number): FanListSelection => ({ accountId: "1000001", fanId, chat: { withUser: { id: fanId } } as OFChatItem });
const arrived: MessagesProSelection = { selected: sel(42), fromLink: true };
const inApp: MessagesProSelection = { selected: sel(7), fromLink: false };
const empty: MessagesProSelection = { selected: null, fromLink: false };

describe("initialMessagesProSelection", () => {
  it.each<[string, FanListSelection | null, MessagesProSelection]>([
    ["a Deep link arrives with its Fan selected", sel(42), arrived],
    ["no Deep link: nothing open", null, empty],
  ])("%s", (_, linked, want) => {
    expect(initialMessagesProSelection(linked)).toEqual(want);
  });
});

describe("messagesProSelectionReducer", () => {
  it.each<[string, MessagesProSelection, MessagesProSelectionAction, MessagesProSelection]>([
    ["a pick after a Deep link ends the arrival", arrived, { type: "select", sel: sel(7) }, { selected: sel(7), fromLink: false }],
    ["re-picking the linked Fan by hand ends it too", arrived, { type: "select", sel: sel(42) }, { selected: sel(42), fromLink: false }],
    ["a pick in the app", inApp, { type: "select", sel: sel(8) }, { selected: sel(8), fromLink: false }],
    ["clear on a Deep link drops both", arrived, { type: "clear" }, empty],
    ["clear in the app", inApp, { type: "clear" }, empty],
  ])("%s", (_, state, action, want) => {
    expect(messagesProSelectionReducer(state, action)).toEqual(want);
  });

  it("clear when nothing is open is a no-op (same state)", () => {
    expect(messagesProSelectionReducer(empty, { type: "clear" })).toBe(empty);
  });
});
