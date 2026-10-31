import { describe, expect, it } from "vitest";

import { chatDrawerReducer, initialChatDrawer, type ChatDrawer, type ChatDrawerAction } from "@/components/chat/chatDrawer";

const closed = initialChatDrawer(false);
const asked: ChatDrawer = { open: true, notesRequest: 2, nicknameRequest: 1 };

describe("chatDrawerReducer", () => {
  it.each<[string, ChatDrawer, ChatDrawerAction, ChatDrawer]>([
    ["toggle opens, nothing focused", closed, { type: "toggle" }, { open: true, notesRequest: 0, nicknameRequest: 0 }],
    ["toggle closes and drops the requests", asked, { type: "toggle" }, closed],
    ["close drops the requests", asked, { type: "close" }, closed],
    ["Notes opens a closed drawer on Notes", closed, { type: "openNotes" }, { open: true, notesRequest: 1, nicknameRequest: 0 }],
    ["Notes on an open drawer raises again", asked, { type: "openNotes" }, { open: true, notesRequest: 3, nicknameRequest: 1 }],
    ["Edit name opens on Nickname", closed, { type: "editName" }, { open: true, notesRequest: 0, nicknameRequest: 1 }],
    ["Edit name on an open drawer raises again", asked, { type: "editName" }, { open: true, notesRequest: 2, nicknameRequest: 2 }],
  ])("%s", (_, state, action, want) => {
    expect(chatDrawerReducer(state, action)).toEqual(want);
  });

  it("close on a closed drawer is a no-op (same state, no re-render)", () => {
    expect(chatDrawerReducer(closed, { type: "close" })).toBe(closed);
  });

  it("close, then Notes, asks once — a stale count never survives a close", () => {
    const s = [{ type: "openNotes" }, { type: "openNotes" }, { type: "close" }, { type: "openNotes" }] as const;
    expect(s.reduce(chatDrawerReducer, closed)).toEqual({ open: true, notesRequest: 1, nicknameRequest: 0 });
  });
});
