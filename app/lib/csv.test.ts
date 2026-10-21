/** csvField: quoting, and formula-looking text opened as text (the server exports' `safe_cell` rule). */
import { describe, expect, it } from "vitest";

import { csvField } from "@/lib/csv";

describe("csvField", () => {
  it.each<[string | number, string]>([
    ["=HYPERLINK(\"http://x\")", "\"'=HYPERLINK(\"\"http://x\"\")\""],
    ["@SUM(A1)", "'@SUM(A1)"],
    ["-cmd", "'-cmd"],
    ["-2+3", "'-2+3"],
    ["--", "'--"],
    ["+cmd", "'+cmd"],
    ["\tx", "'\tx"],
    ["\rx", "\"'\rx\""],
  ])("puts a ' before formula-looking text: %j", (v, want) => {
    expect(csvField(v)).toBe(want);
  });

  it.each<[string | number, string]>([
    [-5, "-5"],
    [-12.5, "-12.5"],
    ["-12.50", "-12.50"],
    ["+3", "+3"],
    ["-", "-"],
    ["—", "—"],
    ["a=b", "a=b"],
    ["a-b", "a-b"],
    ["", ""],
  ])("leaves numbers, numeric text, the lone \"-\" placeholder and other text alone: %j", (v, want) => {
    expect(csvField(v)).toBe(want);
  });

  it.each<[string, string]>([
    ["Beta, Night", "\"Beta, Night\""],
    ["a\"b", "\"a\"\"b\""],
    ["a\nb", "\"a\nb\""],
  ])("quotes a quote, a comma or a line break: %j", (v, want) => {
    expect(csvField(v)).toBe(want);
  });
});
