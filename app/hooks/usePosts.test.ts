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
    [{}, "sq"],
    [{ squarePreview: null }, "pv"],
    [{ squarePreview: null, preview: "" }, "th"],
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
    [{}, ""],
    [{ text: "" }, ""],
    [{ text: "<p>Hello<br/>world</p>" }, "Hello world"],
    [{ text: "a<BR>b<br />c" }, "a b c"],
    [{ text: "<p><b>bold</b> <a href=\"x\">link</a></p>" }, "bold link"],
    [{ text: "  a \n\n\t b  " }, "a b"],
    [{ text: "a &amp; b &lt;3 &gt; &quot;q&quot; &#39;s" }, "a & b <3 > \"q\" 's"],
    [{ text: "a&nbsp;b" }, "a&nbsp;b"],
    [{ text: "&amp;lt;" }, "<"],
    [{ rawText: "raw", text: "<p>html</p>" }, "raw"],
    [{ rawText: "", text: "<p>html</p>" }, ""],
  ])("%j -> %j", (p, want) => {
    expect(postPlainText({ id: 1, ...p })).toBe(want);
  });
});
