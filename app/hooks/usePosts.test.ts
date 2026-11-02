/** usePosts' pure helpers: a post media's thumbnail and a post's plain text. */
import { describe, expect, it } from "vitest";

import { postPlainText, postThumbUrl, type OFPostMedia } from "./usePosts";

describe("postThumbUrl", () => {
  const ALL: OFPostMedia = {
    id: 1,
    squarePreview: "sq",
    preview: "pv",
    thumb: "th",
    files: { preview: { url: "fpv" }, thumb: { url: "fth" } },
    full: "full",
    source: { source: "src" },
  };

  it.each<[Partial<OFPostMedia>, string | null]>([
    // [fields cleared, want] — each row clears the winner of the row before
    [{}, "sq"],
    [{ squarePreview: null }, "pv"],
    [{ squarePreview: null, preview: "" }, "th"], // "" falls through too
    [{ squarePreview: null, preview: null, thumb: null }, "fpv"],
    [{ squarePreview: null, preview: null, thumb: null, files: { preview: null, thumb: { url: "fth" } } }, "fth"],
    [{ squarePreview: null, preview: null, thumb: null, files: null }, "full"],
    [{ squarePreview: null, preview: null, thumb: null, files: null, full: null }, "src"],
    [{ squarePreview: null, preview: null, thumb: null, files: null, full: null, source: { source: null } }, null],
  ])("%j -> %s", (cleared, want) => {
    expect(postThumbUrl({ ...ALL, ...cleared })).toBe(want);
  });

  it("bare media -> null", () => {
    expect(postThumbUrl({ id: 1 })).toBeNull();
  });
});

describe("postPlainText", () => {
  it.each([
    // [post, want]
    [{}, ""],
    [{ text: "" }, ""],
    [{ text: "<p>Hello<br/>world</p>" }, "Hello world"],
    [{ text: "a<BR>b<br />c" }, "a b c"],
    [{ text: "<p><b>bold</b> <a href=\"x\">link</a></p>" }, "bold link"],
    [{ text: "  a \n\n\t b  " }, "a b"],
    [{ text: "a &amp; b &lt;3 &gt; &quot;q&quot; &#39;s" }, "a & b <3 > \"q\" 's"],
    [{ text: "a&nbsp;b" }, "a&nbsp;b"], // as coded: only five entities decode
    [{ text: "&amp;lt;" }, "<"], // BUG: see PR — &amp; decodes first, so an escaped entity decodes twice
    [{ rawText: "raw", text: "<p>html</p>" }, "raw"], // rawText wins
    [{ rawText: "", text: "<p>html</p>" }, ""], // as coded: `??` keeps an empty rawText
  ])("%j -> %j", (p, want) => {
    expect(postPlainText({ id: 1, ...p })).toBe(want);
  });
});
