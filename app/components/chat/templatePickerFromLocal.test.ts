import { describe, expect, it } from "vitest";

import { fromLocal } from "@/components/chat/TemplatePicker";
import type { SavedReply } from "@/lib/relay";

const row = (text: string) => ({ id: 1, account_id: "a", text, price: 0, locked_text: false, media: [] }) as SavedReply;

describe("fromLocal", () => {
  it.each([
    ["bare tags", "hey <b>babe</b>", "hey babe", "<p>hey <strong>babe</strong></p>"],
    ["OF markup", "<p><strong>x</strong></p>", "x", "<p><strong>x</strong></p>"],
    ["prose in angles", "<link in bio>", "<link in bio>", "<link in bio>"],
    ["plain", "hi <3", "hi <3", "hi <3"],
  ])("%s", (_n, text, plain, display) => {
    const t = fromLocal(row(text));
    expect([t.text, t.displayText]).toEqual([plain, display]);
  });
});
