import { describe, expect, it } from "vitest";
import type { OFChatItem } from "@/lib/relay";
import { previewText, previewTitle } from "./fanRowPreview";

type LM = NonNullable<OFChatItem["lastMessage"]>;
const chat = (lm: Partial<LM>): OFChatItem => ({
  __accountId: "7",
  withUser: { id: 9 },
  lastMessage: { id: 1, fromUser: { id: 7 }, ...lm },
} as OFChatItem);

describe("previewText / previewTitle", () => {
  it.each([
    // name, lastMessage, text, title
    ["free text", { text: "hellooo", isFree: true }, "you: hellooo", undefined],
    // OF's own shape for a free chatter/FM text: lockedText true, price 0.
    ["lockedText on a free text: no lock", { text: "hellooo", isFree: true, lockedText: true, price: 0 }, "you: hellooo", undefined],
    ["lockedText without isFree: no lock", { text: "let's talk :))", lockedText: true }, "you: let's talk :))", undefined],
    ["/chats PPV (isFree false, no price)", { text: "<p>new set</p>", isFree: false, mediaCount: 3 }, "you: 🔒 new set", "🔒 paid message (PPV)"],
    ["WS PPV (price > 0)", { text: "set", price: 5 }, "you: 🔒 set", "🔒 paid message (PPV)"],
    ["PPV media only", { isFree: false, mediaCount: 2 }, "you: 🔒 2 media", "🔒 paid message (PPV)"],
    ["tip from fan", { text: "I sent you a $5.00 tip", isTip: true, lockedText: true, fromUser: { id: 9 } }, "💰 I sent you a $5.00 tip", "💰 tip"],
    ["free media only", { isFree: true, mediaCount: 1 }, "you: 📎 1 media", "📎 free media"],
    ["free text + media: no marker", { text: "pic", isFree: true, mediaCount: 1 }, "you: pic", undefined],
    ["fan's text", { text: "hi", fromUser: { id: 9 } }, "hi", undefined],
  ] as const)("%s", (_n, lm, text, title) => {
    const c = chat(lm as Partial<LM>);
    expect(previewText(c)).toBe(text);
    expect(previewTitle(c)).toBe(title);
  });

  it("no last message", () => {
    expect(previewText({ withUser: { id: 9 } } as OFChatItem)).toBe("");
    expect(previewTitle({ withUser: { id: 9 } } as OFChatItem)).toBeUndefined();
  });
});
