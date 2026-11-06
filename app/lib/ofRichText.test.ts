/**
 * lib/ofRichText: OF rich text's allow-list parse, the plain-text helpers every preview uses, and the editor's value
 * contract (lib/ofRichTextEditor), as tables.
 */
import { describe, expect, it } from "vitest";

import {
  decodeEntities, foldBlankParagraphs, hasOfFormatting, isOfHtml, ofPlainText, ofPreviewText, parseOfHtml,
  plainToOfHtml,
} from "@/lib/ofRichText";
import { editorHtmlOf, editorValue, marksAt, plainLength } from "@/lib/ofRichTextEditor";
import { setOfHtml } from "@/lib/ofMirrorFormat";

const run = (text: string, o: Partial<{ bold: boolean; italic: boolean; color: string; size: string }> = {}) =>
  ({ text, bold: !!o.bold, italic: !!o.italic, color: o.color ?? null, size: o.size ?? null });

describe("parseOfHtml", () => {
  const rows: [string, string, unknown][] = [
    ["plain lines", "a\nb", [[run("a")], [run("b")]]],
    ["paragraphs", "<p>a</p><p></p><p>b</p>", [[run("a")], [], [run("b")]]],
    ["OF's nesting", '<p><strong><em><span class="m-editor-fc__blue-1 m-editor-fs__l">x</span></em></strong></p>',
      [[run("x", { bold: true, italic: true, color: "m-editor-fc__blue-1", size: "m-editor-fs__l" })]]],
    ["Infloww's nesting", '<p><span class="m-editor-fc__gray"><strong>x</strong></span>y</p>',
      [[run("x", { bold: true, color: "m-editor-fc__gray" }), run("y")]]],
    ["b / i", "<p><b>x</b><i>y</i></p>", [[run("x", { bold: true }), run("y", { italic: true })]]],
    ["br and folded blank line", "<p>a<br><br>b</p>", [[run("a"), { br: true }, { br: true }, run("b")]]],
    ["foreign class ignored", '<p><span class="evil m-editor-fc__x">x</span></p>', [[run("x")]]],
    ["script dropped whole", "<p>a<script>alert(1)</script>b</p>", [[run("ab")]]],
    ["img / link: text only", '<p><img src=x onerror="a()"><a href="//e">l</a></p>', [[run("l")]]],
    ["entities once", "<p>&amp;lt; &#x1F496; &nbsp;</p>", [[run("&lt; 💖  ")]]],
    ["innermost colour wins", '<p><span class="m-editor-fc__gray">a<span class="m-editor-fc__blue-2">b</span></span></p>',
      [[run("a", { color: "m-editor-fc__gray" }), run("b", { color: "m-editor-fc__blue-2" })]]],
    ["whitespace between paragraphs", "<p>a</p>\n<p>b</p>", [[run("a")], [run("b")]]],
    ["unclosed marks end with the paragraph", "<p><strong>a</p><p>b</p>", [[run("a", { bold: true })], [run("b")]]],
  ];
  it.each(rows)("%s", (_n, html, want) => expect(parseOfHtml(html)).toEqual(want));
});

describe("formatting detection", () => {
  const rows: [string, boolean, boolean][] = [
    ["hi", false, false],
    ["<p>hi</p>", true, false],
    ["<p><strong>hi</strong></p>", true, true],
    ['<p><span class="m-editor-fc__default">hi</span></p>', true, true],
    ['<p><span class="x">hi</span></p>', true, false],
    ["<b>no paragraph</b>", false, false],
    ["  <P>x</P>", true, false],
  ];
  it.each(rows)("%j: html %s, formatted %s", (s, html, fmt) => {
    expect(isOfHtml(s)).toBe(html);
    expect(hasOfFormatting(s)).toBe(fmt);
  });
});

describe("ofPlainText / ofPreviewText", () => {
  const rows: [string, string, string][] = [
    ["<p>a</p><p>b</p>", "a\nb", "a b"],
    ['<p><strong><span class="m-editor-fc__blue-1">Hey</span></strong> you</p>', "Hey you", "Hey you"],
    ["a<br>b<BR />c", "a\nb\nc", "a b c"],
    ["<p>x<script>evil()</script></p>", "x", "x"],
    ["&amp;lt; &#39; &#x41; &nbsp;", "&lt; ' A", "&lt; ' A"],
    ["  plain\n\ntext  ", "plain\n\ntext", "plain text"],
    ["", "", ""],
  ];
  it.each(rows)("%j", (html, plain, preview) => {
    expect(ofPlainText(html)).toBe(plain);
    expect(ofPreviewText(html)).toBe(preview);
  });
  it("decodes an unknown entity as written", () => expect(decodeEntities("&bogus; &#0;")).toBe("&bogus; &#0;"));
});

describe("plainToOfHtml / foldBlankParagraphs", () => {
  it.each([
    ["a\n\nb", "<p>a</p><p></p><p>b</p>"],
    ["x < y & z", "<p>x &lt; y &amp; z</p>"],
  ])("plain %j", (s, want) => expect(plainToOfHtml(s)).toBe(want));
  it.each([
    ["<p>a</p><p></p><p>b</p>", "<p>a<br><br>b</p>"],
    ["<p>a</p><p></p><p></p><p>b</p>", "<p>a<br><br><br><br>b</p>"],
    ["<p>a</p><p>b</p>", "<p>a</p><p>b</p>"],
  ])("fold %j", (s, want) => expect(foldBlankParagraphs(s)).toBe(want));
});

describe("editor value contract", () => {
  const load = (value: string) => {
    const root = document.createElement("div");
    setOfHtml(root, editorHtmlOf(value));
    return root;
  };
  // (stored value, what the untouched editor reads back)
  const rows: [string, string][] = [
    ["plain one line", "plain one line"],
    ["line 1\nline 2", "line 1\nline 2"],
    ["a\n\nb", "a\n\nb"],
    ["\nlead and trail\n\n", "\nlead and trail\n\n"],
    ["  two  spaces ", "  two  spaces "],
    ["", ""],
    ["x < y & z", "x < y & z"],
    ["a &amp; b", "a &amp; b"],
    ["<p>unformatted markup</p>", "unformatted markup"],
    ['<p><strong><span class="m-editor-fc__blue-1 m-editor-fs__l">Hey</span></strong> babe</p>',
      '<p><strong><span class="m-editor-fc__blue-1 m-editor-fs__l">Hey</span></strong> babe</p>'],
    ["<p><em>a</em></p><p></p><p>b</p>", "<p><em>a</em><br><br>b</p>"],
    ['<p><strong>x</strong><img src=x onerror="a()"></p>', "<p><strong>x</strong></p>"],
  ];
  it.each(rows)("%j", (value, want) => expect(editorValue(load(value))).toBe(want));

  it("reads a contenteditable's no-break spaces as spaces", () => {
    const root = document.createElement("div");
    root.innerHTML = "<p>a\u00a0\u00a0b\u00a0</p>";
    expect(editorValue(root)).toBe("a  b ");
  });

  it("counts the plain text against the limit", () => {
    expect(plainLength("abc")).toBe(3);
    expect(plainLength('<p><strong><span class="m-editor-fs__lg">abc</span></strong></p>')).toBe(3);
  });

  it("reads the caret's marks", () => {
    const root = load('<p><strong><span class="m-editor-fc__gray m-editor-fs__s">x</span></strong>y</p>');
    const x = root.querySelector("span")!.firstChild;
    const y = root.querySelector("p")!.lastChild;
    expect(marksAt(root, x)).toEqual({ bold: true, italic: false, color: "m-editor-fc__gray", size: "m-editor-fs__s" });
    expect(marksAt(root, y)).toEqual({ bold: false, italic: false, color: null, size: null });
    expect(marksAt(root, document.createTextNode("out"))).toEqual({ bold: false, italic: false, color: null, size: null });
  });
});
