import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { applyData } from "./ofMirrorData";
import { chatRowsOf, chatUser, pendingPartners, usersListPath, withChatUsers } from "./ofMirrorDataQueries";
import { rowsOf } from "./ofMirrorPaging";
import type { OFChatItem, OFMessage, OFUserMini } from "./relay";
import { load, shown, texts, PLACEHOLDER } from "./ofMirrorData.fixtures";

/** OF's own /api2/v2 responses for Messages, captured through the Relay and scrubbed (app/lib/__fixtures__/of). */
const msgFixture = <T,>(name: string): T => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/messages-${name}.json`), "utf8")) as T;

describe("Messages from OF's captured responses (app/lib/__fixtures__/of)", () => {
  const listed = rowsOf<OFChatItem>(msgFixture("chats"))!;
  const users = msgFixture<Record<string, OFUserMini & { displayName?: string }>>("users-list");
  const MODEL = 1001; // the Creator's id in the fixtures
  const img = (u: string) => `/img?u=${u}`;

  it("/chats sends each partner bare (an id); withChatUsers fills in its name, handle and avatar from /users/list", () => {
    expect(listed).toHaveLength(20);
    for (const c of listed) expect(Object.keys(c.withUser).sort()).toEqual(["_view", "id"]);
    const rows = withChatUsers(listed, users);
    for (const c of rows) {
      const u = users[String(c.withUser.id)];
      expect(c.withUser).toMatchObject({ id: c.withUser.id, username: u.username, avatar: u.avatar, name: u.displayName || u.name });
    }
    // OF answers [] when it resolves none; a partner it did not return keeps its id.
    expect(withChatUsers(listed, [])).toEqual(listed);
    const { [String(listed[0].withUser.id)]: _dropped, ...rest } = users;
    expect(withChatUsers(listed, rest)[0]).toBe(listed[0]);
  });

  it("usersListPath: one ids= per partner", () => {
    expect(usersListPath(["2001", "2002"])).toBe("/api/of/v2/users/list?ids=2001&ids=2002");
  });

  it("chatUser: the Creator's rename (displayName) wins over the name; a blank one keeps it", () => {
    const opened = msgFixture<OFChatItem>("chat").withUser as OFUserMini;
    expect(opened.displayName).toBeTruthy();
    expect(chatUser(opened).name).toBe(opened.displayName);
    expect(chatUser({ ...opened, displayName: " " }).name).toBe(opened.name);
  });

  it("messages/index: one row per captured chat, its partner's name, @handle, avatar and last message; no example left", () => {
    const doc = load("messages/index");
    const rows = withChatUsers(listed, users);
    applyData(doc, "messages/index", { chats: rows }, img);
    expect(texts(doc, ".b-chats__item .g-user-name")).toEqual(rows.map((c) => c.withUser.name));
    expect(texts(doc, ".b-chats__item .g-user-username")).toEqual(rows.map((c) => `@${c.withUser.username}`));
    expect(shown(doc, ".b-chats__item__link").map((a) => a.getAttribute("href"))).toEqual(rows.map((c) => `/of-manager/messages/chat?chat=${c.withUser.id}`));
    expect(shown(doc, ".b-chats__item .g-avatar img").map((i) => i.getAttribute("src"))).toEqual(rows.map((c) => img(c.withUser.avatar!)));
    expect(texts(doc, ".b-chats__item__last-message__content")).toEqual(rows.map((c) => (c.lastMessage?.text ?? "").replace(/<[^>]+>/g, "") || (c.lastMessage?.mediaCount ? "Media" : "")));
    expect(shown(doc, ".b-chats__item.m-unread")).toEqual([]); // every captured chat is read
    for (const r of shown(doc, ".b-chats__item")) expect(r.textContent).not.toMatch(PLACEHOLDER);
    expect(shown(doc, ".b-chats__scroller [data-oi-empty]").filter((e) => !(e as HTMLElement).style.display.includes("none"))).toEqual([]);
  });

  it("the Pinned and oldest-first reads list the same rows; Priority and Unread with none show OF's Nothing found", () => {
    for (const name of ["chats-pinned", "chats-oldest"]) {
      const doc = load("messages/index");
      const rows = rowsOf<OFChatItem>(msgFixture(name))!;
      expect(rows.length, name).toBeGreaterThan(0);
      applyData(doc, "messages/index", { chats: rows });
      expect(shown(doc, ".b-chats__item"), name).toHaveLength(rows.length);
    }
    for (const name of ["chats-priority", "chats-unread"]) {
      const doc = load("messages/index");
      expect(msgFixture(name), name).toEqual({ list: [], hasMore: false });
      applyData(doc, "messages/index", { chats: rowsOf<OFChatItem>(msgFixture(name))! });
      expect(texts(doc, ".b-chats__scroller [data-oi-empty] .empty-message"), name).toEqual(["Nothing found"]);
    }
    // OF has no "tips" filter (the page's With Tips tab stays disabled): the Relay passes on its 400.
    expect(JSON.stringify(msgFixture("chats-with-tips"))).toContain("Invalid filter");
  });

  it("messages/chat: the captured thread, oldest first, the Creator's own messages on its side, media in OF's bubble and PPV prices", () => {
    const doc = load("messages/chat");
    const detail = msgFixture<OFChatItem>("chat");
    const messages = rowsOf<OFMessage>(msgFixture("thread"))!;
    const chat = String(detail.withUser.id);
    applyData(doc, "messages/chat", { chat, chats: withChatUsers(listed, users), thread: { fan: chatUser(detail.withUser), messages } }, img);
    expect(texts(doc, ".b-chat__header__title span.g-user-name")).toEqual([detail.withUser.displayName]);
    const sorted = [...messages].sort((a, b) => Date.parse(a.createdAt!) - Date.parse(b.createdAt!));
    const bubbles = shown(doc, ".b-chat__messages-wrapper .b-chat__message");
    expect(bubbles).toHaveLength(messages.length);
    expect(bubbles.map((b) => b.classList.contains("m-from-me"))).toEqual(sorted.map((m) => m.fromUser?.id === MODEL));
    expect(bubbles.map((b) => b.querySelectorAll(".b-chat__message__media").length > 0)).toEqual(sorted.map((m) => (m.media ?? []).some((x) => x.canView !== false && !!x.files)));
    const ppv = sorted.filter((m) => (m.price ?? 0) > 0 && !m.isTip);
    expect(ppv.length).toBeGreaterThan(0);
    expect(bubbles.filter((b) => b.querySelector(".b-chat__message__payment-state"))).toHaveLength(ppv.length);
    for (const b of bubbles) expect(b.textContent).not.toMatch(PLACEHOLDER);
    expect(texts(doc, ".b-chats__item.current .g-user-name")).toEqual([detail.withUser.displayName]);
  });
});

describe("the chat list's rows and their partners (chatRowsOf, pendingPartners)", () => {
  const bare = (id: number) => ({ withUser: { id } }) as OFChatItem;
  const named = (id: number) => ({ id, name: `Name ${id}`, username: `u${id}` });
  const users = (...ids: number[]) => Object.fromEntries(ids.map((id) => [String(id), named(id)]));
  it("a first read waits for its partners (no bare ids): the list is loading", () => {
    expect(chatRowsOf([[bare(1), bare(2)]], [["1", "2"]], [{ isPending: true }], {})).toBeUndefined();
    expect(chatRowsOf([[bare(1), bare(2)]], [["1", "2"]], [{ isPending: false, data: users(1, 2) }], {})!.map((c) => c.withUser.name)).toEqual(["Name 1", "Name 2"]);
  });
  it("a new chat at the top (a new /users/list key) keeps the known rows instead of the whole list loading again", () => {
    const rows = chatRowsOf([[bare(3), bare(1), bare(2)]], [["1", "2", "3"]], [{ isPending: true }], users(1, 2))!;
    expect(rows.map((c) => c.withUser.name)).toEqual(["Name 1", "Name 2"]); // 3 shows once it is named
  });
  it("a later page still asking stops the list there; a chat on two pages shows once", () => {
    const rows = chatRowsOf([[bare(1)], [bare(1), bare(4)]], [["1"], ["1", "4"]], [{ isPending: false, data: users(1) }, { isPending: false, data: users(1, 4) }], {})!;
    expect(rows.map((c) => c.withUser.id)).toEqual([1, 4]);
    expect(chatRowsOf([[bare(1)], [bare(5)]], [["1"], ["5"]], [{ isPending: false, data: users(1) }, { isPending: true }], users(1))!.map((c) => c.withUser.id)).toEqual([1]);
  });
  it("a page with no partner ids (its read disabled, pending for ever in TanStack) never holds the paging", () => {
    expect(pendingPartners([[]], [{ isPending: true }])).toBe(false);
    expect(pendingPartners([["1"], []], [{ isPending: false }, { isPending: true }])).toBe(false);
    expect(pendingPartners([["1"]], [{ isPending: true }])).toBe(true);
    expect(chatRowsOf([[], [bare(1)]], [[], ["1"]], [{ isPending: true }, { isPending: false, data: users(1) }], {})!.map((c) => c.withUser.id)).toEqual([1]);
  });
});
