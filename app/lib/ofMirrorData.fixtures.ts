/** The OF mirror tests' shared helpers and rows (cut from ofMirrorData.test.ts): captured pages, OF's fixture chats, the borrowed post row. */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";
import type { MirrorData } from "./ofMirrorDataOf";
import { TEMPLATES } from "./ofMirrorFeedsShared";
import type { OFChatItem, OFMessage } from "./relay";

export const capture = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
export const load = (p: string) => {
  document.documentElement.innerHTML = capture(p);
  return document;
};
/** Not inside a hidden example. */
export const visible = (el: Element) => !el.closest("[style*='display:none']");
export const shown = (doc: Document, sel: string) => [...doc.querySelectorAll(sel)].filter(visible);
export const texts = (doc: Document, sel: string) => shown(doc, sel).map((e) => e.textContent?.trim());
/** Run `fn` at the fixtures' "now", 2026-10-10 14:05 local: OF's feed times (feedTime) then read as the expectations say. */
export const atFixtureNow = (fn: () => void) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-10T14:05:00"));
  try {
    fn();
  } finally {
    vi.useRealTimers();
  }
};
export const PLACEHOLDER = /Fan \d|@fan\d|Lorem|List \d/;

export const fan = (id: number, name: string, username: string) => ({ id, name, username, avatar: `https://cdn.example/${username}.jpg` });
export const CHATS: OFChatItem[] = [
  { withUser: fan(101, "Alpha One", "alpha"), lastMessage: { id: 1, text: "<p>hey there</p>", createdAt: "2026-10-10T10:00:00Z" }, unreadMessagesCount: 2 },
  { withUser: fan(102, "Beta Two", "beta"), lastMessage: { id: 2, text: "see you", createdAt: "2026-10-09T10:00:00Z" } },
  { withUser: fan(103, "Gamma Three", "gamma"), lastMessage: { id: 3, text: "", mediaCount: 1, createdAt: "2026-10-08T10:00:00Z" } },
];
export const msg = (id: number, from: number, text: string, at: string) => ({ id, text, fromUser: { id: from }, createdAt: at, media: [] }) as OFMessage;
// Newest first, as the relay sends them.
export const MESSAGES = [
  msg(4, 1, "fourth from me", "2026-10-10T09:03:00Z"),
  msg(3, 102, "third from fan", "2026-10-10T09:02:00Z"),
  msg(2, 1, "<p>second from me</p>", "2026-10-09T09:01:00Z"),
  msg(1, 102, "first from fan", "2026-10-09T09:00:00Z"),
];
export const CHAT: MirrorData = { chat: "102", chats: CHATS, thread: { fan: CHATS[1].withUser, messages: MESSAGES } };

// The `post` template as useOfData borrows it: My profile's capture, parsed inertly.
export const POST_TPL = TEMPLATES.post!.pick(new DOMParser().parseFromString(capture(TEMPLATES.post!.page), "text/html"))!;
