import { describe, expect, it } from "vitest";

import { compileWords, matchSensitiveWords, tabOf } from "@/lib/sensitiveWords";

const hits = (text: string, words: string[]) => matchSensitiveWords(text, compileWords(words));

describe("matchSensitiveWords (Infloww's matcher)", () => {
  it("matches whole words in any case, never inside another word", () => {
    expect(hits("Send it to my Venmo please", ["venmo"])).toEqual(["venmo"]);
    expect(hits("VENMO", ["venmo"])).toEqual(["venmo"]);
    expect(hits("first class pass", ["ass"])).toEqual([]);
    expect(hits("venmoo", ["venmo"])).toEqual([]);
  });

  it("treats punctuation, symbols and emoji as boundaries", () => {
    expect(hits("(venmo)!", ["venmo"])).toEqual(["venmo"]);
    expect(hits("@venmo, ok", ["venmo"])).toEqual(["venmo"]);
    expect(hits("venmo😘", ["venmo"])).toEqual(["venmo"]);
    expect(hits("pay-venmo", ["venmo"])).toEqual(["venmo"]);
  });

  it("matches a phrase across any run of whitespace", () => {
    expect(hits("use cash   app now", ["cash app"])).toEqual(["cash app"]);
    expect(hits("use cash\napp", ["cash app"])).toEqual(["cash app"]);
    expect(hits("use cashapp", ["cash app"])).toEqual([]);
  });

  it("matches a word holding an emoji against the raw text", () => {
    expect(hits("you are 🍑 hot", ["🍑"])).toEqual(["🍑"]);
    expect(hits("hot 🍑 now", ["hot 🍑"])).toEqual(["hot 🍑"]);
    expect(hits("hot now", ["🍑"])).toEqual([]);
  });

  it("reports each listed word once, in list order, and escapes regex characters", () => {
    expect(hits("venmo or paypal or venmo", ["paypal", "venmo"])).toEqual(["paypal", "venmo"]);
    expect(hits("visit onlyfans.com", ["onlyfans.com"])).toEqual(["onlyfans.com"]);
    expect(hits("visit onlyfansXcom", ["onlyfans.com"])).toEqual([]);
    expect(hits("a+b", ["a+b"])).toEqual(["a+b"]);
  });

  it("is a no-op on empty text or an empty list", () => {
    expect(hits("", ["venmo"])).toEqual([]);
    expect(hits("venmo", [])).toEqual([]);
    expect(hits("venmo", ["  "])).toEqual([]);
  });
});

describe("tabOf", () => {
  it("files a word under its first letter, else Special symbol", () => {
    expect(tabOf("venmo")).toBe("V");
    expect(tabOf(" Zelle")).toBe("Z");
    expect(tabOf("123")).toBe("Special symbol");
    expect(tabOf("🍑")).toBe("Special symbol");
  });
});
