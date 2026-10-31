import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { mergeCaptions, parseCaptions, type CaptionFormat } from "@/lib/parseCaptions";

describe("parseCaptions", () => {
  it.each<[string, string, string | undefined, CaptionFormat, string[]]>([
    ["json string array", '["a", " b ", "", "a"]', undefined, "json", ["a", "b"]],
    ["json objects, first known field", '[{"caption":"x"},{"text":"y","caption":"z"},{"id":1}]', undefined, "json", ["x", "y"]],
    ["json object holding an array", '{"captions":["p","q"]}', undefined, "json", ["p", "q"]],
    ["json object, singular key", '{"messages":[{"content":"m"}], "text":["t1","t2"]}', undefined, "json", ["t1", "t2"]],
    ["broken json falls through to text", "[not json\nsecond", undefined, "text", ["[not json", "second"]],
    ["csv quoted cells, \"\" escapes, embedded newline", '"a, b"\r\n"say ""hi"""\n"multi\nline"\nplain', "x.csv", "csv",
      ["a, b", 'say "hi"', "multi\nline", "plain"]],
    ["csv header picks its column", "id,caption,notes\n1,hello,n1\n2,\"bye, now\",n2", "x.csv", "csv", ["hello", "bye, now"]],
    ["csv no header → first column", "one,1\ntwo,2", "x.csv", "csv", ["one", "two"]],
    ["semicolon delimiter", "Text;Price\nhey;5\nyo;6", "x.csv", "csv", ["hey", "yo"]],
    ["tab paste is tabular", "Caption\tn\nhi\t1\nho\t2", undefined, "csv", ["hi", "ho"]],
    ["single-column csv with a sloppy comma", 'first one\nhey, you\n"quoted, ok"', "x.csv", "csv",
      ["first one", "hey, you", "quoted, ok"]],
    ["csv header 'variants'", "variants\nv1\nv2", "x.csv", "csv", ["v1", "v2"]],
    ["paste with commas stays text", "hey, babe\nwhat's up, cutie", undefined, "text", ["hey, babe", "what's up, cutie"]],
    ["paste of clean quoted lines is csv", '"a, b"\n"c ""d"""', undefined, "csv", ["a, b", 'c "d"']],
    ["text unquotes a bare quoted line", '"wrapped"\n"Hi" she said\n\n  spaced  \nwrapped', undefined, "text",
      ["wrapped", '"Hi" she said', "spaced"]],
    [".txt never parsed as csv", '"a, b"\nc', "notes.txt", "text", ["a, b", "c"]],
    ["BOM + CR-only lines", "﻿x\ry\rx", undefined, "text", ["x", "y"]],
    ["empty", "  \n\n ", undefined, "text", []],
  ])("%s", (_name, text, filename, format, items) => {
    expect(parseCaptions(text, { filename })).toEqual({ items, format });
  });

  it("parses the real 251-row caption file intact", () => {
    const raw = readFileSync(join(__dirname, "__fixtures__/captions-general.csv"), "utf8");
    const { items, format } = parseCaptions(raw, { filename: "captions-general.csv" });
    expect(format).toBe("csv");
    expect(items.length).toBe(251);
    expect(items[0]).toBe("sometimes i reply with words, sometimes with pics. depends how good your opener is 😉");
    expect(items).toContain('HOT POTATO! Send me a "🤍" in dms real quick!');
    expect(items).toContain("i have an excuse to ruin my sleep schedule and text all night 💘💘");
    // Nothing mangled: no leftover quotes/CRs, no lone surrogates (cut emoji).
    for (const it of items) {
      expect(it).not.toMatch(/^"|"$|\r/);
      expect(it).toBe(it.trim());
      expect(it.isWellFormed()).toBe(true);
    }
    // Every emoji in the file survives.
    const emoji = (s: string) => s.match(/\p{Extended_Pictographic}/gu)?.length ?? 0;
    expect(items.reduce((n, it) => n + emoji(it), 0)).toBe(emoji(raw));
  });
});

describe("mergeCaptions", () => {
  it.each<[string, string[], string[], number | undefined, ReturnType<typeof mergeCaptions>]>([
    ["replaces a lone blank", [""], ["a", "b"], undefined, { pool: ["a", "b"], added: ["a", "b"], dupes: 0, dropped: 0 }],
    ["appends to a filled pool", ["x"], ["a"], undefined, { pool: ["x", "a"], added: ["a"], dupes: 0, dropped: 0 }],
    ["appends after a blank among others", ["x", ""], ["a"], undefined, { pool: ["x", "", "a"], added: ["a"], dupes: 0, dropped: 0 }],
    ["skips exact dupes of the pool", ["a"], ["a", "b"], undefined, { pool: ["a", "b"], added: ["b"], dupes: 1, dropped: 0 }],
    ["caps at max", [""], ["a", "b", "c"], 2, { pool: ["a", "b"], added: ["a", "b"], dupes: 0, dropped: 1 }],
    ["caps counting the existing pool", ["x"], ["a", "b"], 2, { pool: ["x", "a"], added: ["a"], dupes: 0, dropped: 1 }],
    ["full pool → unchanged", ["x", "y"], ["a"], 2, { pool: ["x", "y"], added: [], dupes: 0, dropped: 1 }],
    ["empty pool (nudge lines)", [], ["a"], undefined, { pool: ["a"], added: ["a"], dupes: 0, dropped: 0 }],
    ["nothing to add keeps the lone blank", [""], [], undefined, { pool: [""], added: [], dupes: 0, dropped: 0 }],
  ])("%s", (_name, pool, items, max, want) => {
    expect(mergeCaptions(pool, items, max)).toEqual(want);
  });
});
