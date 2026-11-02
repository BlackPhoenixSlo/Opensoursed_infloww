/**
 * lib/messageFormat — `htmlToText`, the one copy of the line-keeping HTML → text that MassMessageRow, ScheduledTab
 * and TemplatePicker each carried. The legacy column proves it prints exactly what their copies did.
 */
import { describe, expect, it } from "vitest";

import { htmlToText } from "@/lib/messageFormat";

/** The components' `stripHtml` copy before the move, verbatim. */
function legacyStripHtml(s: string): string {
  return s
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .trim();
}

describe("htmlToText", () => {
  const rows: [string, string][] = [
    ["<p>a</p><p>b</p>", "a\nb"],
    ["a<br>b", "a\nb"],
    ["a<BR />b", "a\nb"],
    ["<br/>", ""],
    ["&amp; &nbsp; &#39; &lt;b&gt; &quot;", "&   ' <b> \""],
    ["<p><b><i>x</i></b></p>", "x"],
    ["  a   b  ", "a   b"],
    ["", ""],
  ];
  it.each(rows)("%j → %j", (html, want) => {
    expect(htmlToText(html)).toBe(want);
    expect(htmlToText(html)).toBe(legacyStripHtml(html));
  });
});
