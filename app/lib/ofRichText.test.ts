/**
 * lib/ofRichText: OF rich text's allow-list parse, the plain-text helpers every preview uses, and the editor's value
 * contract (lib/ofRichTextEditor), as tables. `hasHtml` / `ofText` / `ofPlain` and the relay's `has_html` / `of_text` /
 * `of_plain` assert one table (service/tests/fixtures/of_rich_text_cases.json, read at runtime: it lives with the
 * python test data, outside the Next tsconfig's rootDir).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ACTIVE, BLOCK, decodeEntities, foldBlankParagraphs, hasHtml, hasOfFormatting, isOfHtml, KNOWN, ofPlain, ofPlainText,
  ofPreviewText, ofText, parseOfHtml, plainToOfHtml, sanitizeOfHtml,
} from "@/lib/ofRichText";
import {
  clearAtCaret, cutTo, editorHtmlOf, editorValue, marksAt, NO_MARKS, pastedOfHtml, plainLength, tidy,
} from "@/lib/ofRichTextEditor";
import { setOfHtml } from "@/lib/ofMirrorFormat";

const run = (text: string, o: Partial<{ bold: boolean; italic: boolean; color: string; size: string }> = {}) =>
  ({ text, bold: !!o.bold, italic: !!o.italic, color: o.color ?? null, size: o.size ?? null });

describe("parseOfHtml", () => {
  const rows: [string, string, unknown][] = [
    ["plain lines", "a\nb", [[run("a")], [run("b")]]],
    ["paragraphs", "<p>a</p><p></p><p>b</p>", [[run("a")], [], [run("b")]]],
    ["OF's nesting", '<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong><em>x</em></strong></span></p>',
      [[run("x", { bold: true, italic: true, color: "m-editor-fc__blue-1", size: "m-editor-fs__l" })]]],
    ["legacy nesting (strong > em > span)", '<p><strong><em><span class="m-editor-fc__blue-1 m-editor-fs__l">x</span></em></strong></p>',
      [[run("x", { bold: true, italic: true, color: "m-editor-fc__blue-1", size: "m-editor-fs__l" })]]],
    ["Infloww's nesting", '<p><span class="m-editor-fc__gray"><strong>x</strong></span>y</p>',
      [[run("x", { bold: true, color: "m-editor-fc__gray" }), run("y")]]],
    ["b / i", "<p><b>x</b><i>y</i></p>", [[run("x", { bold: true }), run("y", { italic: true })]]],
    ["br and folded blank line", "<p>a<br><br>b</p>", [[run("a"), { br: true }, { br: true }, run("b")]]],
    ["foreign class ignored", '<p><span class="evil m-editor-fc__x">x</span></p>', [[run("x")]]],
    ["script dropped whole", "<p>a<script>alert(1)</script>b</p>", [[run("ab")]]],
    ["img / link: text only", '<p><img src=x onerror="a()"><a href="//e">l</a></p>', [[run("l")]]],
    ["entities once (`&nbsp;` stays U+00A0)", "<p>&amp;lt; &#x1F496; &nbsp;</p>", [[run("&lt; 💖 \u00a0")]]],
    ["innermost colour wins", '<p><span class="m-editor-fc__gray">a<span class="m-editor-fc__blue-2">b</span></span></p>',
      [[run("a", { color: "m-editor-fc__gray" }), run("b", { color: "m-editor-fc__blue-2" })]]],
    ["whitespace between paragraphs", "<p>a</p>\n<p>b</p>", [[run("a")], [run("b")]]],
    ["unclosed marks end with the paragraph", "<p><strong>a</p><p>b</p>", [[run("a", { bold: true })], [run("b")]]],
  ];
  it.each(rows)("%s", (_n, html, want) => expect(parseOfHtml(html)).toEqual(want));
});

interface SharedCase { name: string; text: string; markup: boolean; sent: string; plain: string }
type Names = Record<"known" | "active" | "blocks" | "drop" | "unknown", string[]>;
/** Built as `parts` concatenated (`[piece, times]`); has_html + of_text + of_plain within the fixture's max_ms. */
type PerfRow = { name: string; parts: [string, number][] };
const FIXTURE = JSON.parse(readFileSync(
  join(__dirname, "..", "..", "service", "tests", "fixtures", "of_rich_text_cases.json"), "utf8",
)) as { cases: SharedCase[]; names: Names; perf: { max_ms: number; rows: PerfRow[] } };
const SHARED = FIXTURE.cases;

/** Rows from the fixture's name lists, as service/tests/test_of_rich_text.py `name_rows`: [text, markup, plain]. */
function nameRows(names: Names): [string, boolean, string | null][] {
  const [known, active, blocks, drop] = (["known", "active", "blocks", "drop"] as const).map((k) => new Set(names[k]));
  const pool = [...new Set([...known, ...active, ...blocks, ...drop, ...names.unknown])].sort();
  return pool.flatMap((n) => {
    const tag = known.has(n) || active.has(n);
    const rows: [string, boolean, string | null][] = [
      // prose in angles: plain unless an active name (or `<p `: OF's own markup starts so, `isOfHtml`)
      [`<${n} coming soon>`, active.has(n) || n === "p", null],
      [`x <${n} id=1>y`, true, null], // a known name: bare formatting; any other: fails closed
      [`<${n}>`, tag, null],
    ];
    if (n !== "p" && n !== "br") {
      rows.push([`<p>a<${n}>b</${n}>c</p>`, true, drop.has(n) ? "ac" : blocks.has(n) ? "a\nb\nc" : "abc"]);
    }
    return rows;
  });
}

describe("shared table with the relay (has_html / of_text / of_plain)", () => {
  it("has cases to check", () => expect(SHARED.length).toBeGreaterThanOrEqual(30));
  const rows = nameRows(FIXTURE.names);
  it("has name rows to check", () => expect(rows.length).toBeGreaterThan(300));
  it("copies the fixture's name lists", () => {
    expect([[...KNOWN].sort(), [...ACTIVE].sort(), [...BLOCK].sort()])
      .toEqual([FIXTURE.names.known, FIXTURE.names.active, FIXTURE.names.blocks]);
  });
  it.each(rows)("names: %j", (text, markup, plain) => {
    expect(hasHtml(text)).toBe(markup);
    if (plain !== null) expect(ofPlain(text)).toBe(plain);
  });
  it.each(FIXTURE.perf.rows.map((r) => [r.name, r] as const))("perf: %s", (_n, r) => {
    const text = r.parts.map(([piece, n]) => piece.repeat(n)).join("");
    const t = performance.now();
    hasHtml(text);
    ofText(text);
    ofPlain(text);
    expect(performance.now() - t).toBeLessThan(FIXTURE.perf.max_ms);
  });
  it.each(SHARED.map((c) => [c.name, c] as const))("%s", (_n, c) => {
    expect(hasHtml(c.text)).toBe(c.markup);
    expect(ofText(c.text)).toBe(c.sent);
    expect(ofPlain(c.text)).toBe(c.plain);
  });
  // The editor's escape decision is the relay's: typed text it would read as markup is stored escaped (the fan reads
  // what was typed), anything else stays the plain text.
  // (U+00A0 aside: the editor's plain text writes it as a space, by design.)
  it.each(SHARED.filter((c) => c.text && !/[\r\n\u00a0]/.test(c.text)).map((c) => [c.name, c] as const))("editor: %s", (_n, c) => {
    const root = document.createElement("div");
    const p = document.createElement("p");
    p.textContent = c.text;
    root.append(p);
    const v = editorValue(root);
    if (c.markup) {
      expect(v).not.toBe(c.text);
      expect(ofPlain(v)).toBe(c.text);
      expect(ofText(v)).toBe(v);
    } else expect(v).toBe(c.text);
  });
});

describe("formatting detection", () => {
  const rows: [string, boolean, boolean][] = [
    ["hi", false, false],
    ["<p>hi</p>", true, false],
    ["<p><strong>hi</strong></p>", true, true],
    ['<p><span class="m-editor-fc__default">hi</span></p>', true, true],
    ['<p><span class="x">hi</span></p>', true, false],
    ["<b>no paragraph</b>", false, true], // bare tags: the relay sends them as markup (`ofText`)
    ["<i love you>", false, false],
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
    ['<p><span class="m-editor-fc__blue-1"><strong>Hey</strong></span> you</p>', "Hey you", "Hey you"],
    ["a<br>b<BR />c", "a\nb\nc", "a b c"],
    ["<p>x<script>evil()</script></p>", "x", "x"],
    ["&amp;lt; &#39; &#x41; &nbsp;", "&lt; ' A", "&lt; ' A"],
    ["  plain\n\ntext  ", "plain\n\ntext", "plain text"],
    ["code <VIP20>", "code <VIP20>", "code <VIP20>"], // tag-shaped prose is not a tag
    ["<p>a</p><blockquote>b</blockquote>", "a\nb", "a b"],
    ["<br/>", "", ""],
    ["&amp; &nbsp; &#39; &lt;b&gt; &quot;", "&   ' <b> \"", "& ' <b> \""],
    ["<p><b><i>x</i></b></p>", "x", "x"],
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
    ["<p>a</p><p></p><p></p><p>b</p>", "<p>a<br><br><br>b</p>"], // n blanks = n+1 <br>: plain keeps n blank lines (D)
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
    ['<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>Hey</strong></span> babe</p>',
      '<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>Hey</strong></span> babe</p>'],
    ["<p><em>a</em></p><p></p><p>b</p>", "<p><em>a</em><br><br>b</p>"],
    ['<p><strong>x</strong><img src=x onerror="a()"></p>', "<p><strong>x</strong></p>"],
  ];
  it.each(rows)("%j", (value, want) => expect(editorValue(load(value))).toBe(want));

  it("reads a contenteditable's no-break spaces as spaces", () => {
    const root = document.createElement("div");
    root.innerHTML = "<p>a\u00a0\u00a0b\u00a0</p>";
    expect(editorValue(root)).toBe("a  b ");
  });

  it.each<[string, number, string]>([
    ["ab\u{1F496}c", 3, "ab"], ["ab\u{1F496}c", 4, "ab\u{1F496}"], ["abc", 2, "ab"], ["abc", -1, ""], ["abc", Infinity, "abc"],
  ])("cuts %j to %i units on a code point", (s, n, want) => expect(cutTo(s, n)).toBe(want));

  it("counts the plain text against the limit", () => {
    expect(plainLength("abc")).toBe(3);
    expect(plainLength('<p><span class="m-editor-fs__lg"><strong>abc</strong></span></p>')).toBe(3);
  });

  it("reads the caret's marks", () => {
    const root = load('<p><span class="m-editor-fs__s m-editor-fc__gray"><strong>x</strong></span>y</p>');
    const x = root.querySelector("span")!.firstChild;
    const y = root.querySelector("p")!.lastChild;
    expect(marksAt(root, x)).toEqual({ bold: true, italic: false, color: "m-editor-fc__gray", size: "m-editor-fs__s" });
    expect(marksAt(root, y)).toEqual({ bold: false, italic: false, color: null, size: null });
    expect(marksAt(root, document.createTextNode("out"))).toEqual({ bold: false, italic: false, color: null, size: null });
  });
});

describe("entities, quoted '>' and block tags (item 7)", () => {
  it.each<[string, string]>([
    ["&hellip; &rsquo; &eacute; &mdash;", "\u2026 \u2019 \u00e9 \u2014"],
    ["&amp;hellip;", "&hellip;"], // decoded once
    ["&notanentity;", "&notanentity;"],
  ])("decode %j", (s, want) => expect(decodeEntities(s)).toBe(want));

  it("a '>' inside a quoted attribute does not end the tag", () => {
    const html = '<p><span title="a>b" class="m-editor-fc__blue-1">Hey</span> you</p>';
    expect(parseOfHtml(html)).toEqual([[run("Hey", { color: "m-editor-fc__blue-1" }), run(" you")]]);
    expect(ofPlainText(html)).toBe("Hey you");
  });

  it.each<[string, string, unknown]>([
    ["div lines", "<div>a</div><div>b</div>", [[run("a")], [run("b")]]],
    ["list items", "<ul><li>a</li><li><strong>b</strong></li></ul>", [[run("a")], [run("b", { bold: true })]]],
    ["headings", "<h1>a</h1><h6>b</h6>", [[run("a")], [run("b")]]],
    ["p inside li is one line", "<ul><li><p>a</p></li></ul>", [[run("a")]]],
  ])("%s are paragraphs", (_n, html, want) => {
    expect(parseOfHtml(html)).toEqual(want);
    expect(ofPlainText(html)).toBe((want as { text: string }[][]).map((p) => p.map((r) => r.text).join("")).join("\n"));
  });

  it("sanitizeOfHtml keeps only OF's allow-list", () => {
    expect(sanitizeOfHtml('<p><b>a</b><img src=x onerror="x()"><span class="m-editor-fs__l evil">b</span></p><div>c</div>'))
      .toBe('<p><strong>a</strong><span class="m-editor-fs__l">b</span></p><p>c</p>');
  });
});

describe("Codex A: typed text that looks like markup round-trips as text", () => {
  const typed = (text: string) => {
    const root = document.createElement("div");
    const p = document.createElement("p");
    p.textContent = text;
    root.append(p);
    return root;
  };
  it.each<string>(["<p>Use <VIP20></p>", "<p>", "<P class=x>hi", "Use <b>bold</b> literally"])("%j", (text) => {
    const v = editorValue(typed(text));
    expect(v).not.toBe(text); // emitted escaped, never as live markup
    expect(ofPlainText(v)).toBe(text); // the fan reads what was typed
    const back = document.createElement("div");
    setOfHtml(back, editorHtmlOf(v));
    expect(editorValue(back)).toBe(v); // stable on reload
    expect(back.textContent).toBe(text);
  });
  it("text the relay reads as plain stays plain", () =>
    expect(editorValue(typed("Use <VIP20> now"))).toBe("Use <VIP20> now"));
  it("bare markup (an imported cell) loads as the formatting it sends as", () => {
    const back = document.createElement("div");
    setOfHtml(back, editorHtmlOf("hey <b>babe</b>\nyo"));
    expect(editorValue(back)).toBe("<p>hey <strong>babe</strong><br>yo</p>");
  });
});

describe("Codex D: blank lines survive plain -> markup -> plain", () => {
  it.each<number>([0, 1, 2, 3, 5])("%i blank lines", (n) => {
    const plain = `a${"\n".repeat(n + 1)}b`;
    expect(ofPlainText(foldBlankParagraphs(plainToOfHtml(plain)))).toBe(plain);
    const root = document.createElement("div");
    setOfHtml(root, editorHtmlOf(`<p><em>a</em></p>${"<p></p>".repeat(n)}<p>b</p>`));
    expect(ofPlainText(editorValue(root))).toBe(plain);
  });
});

describe("Codex B: Clear formatting at a caret inside a mark", () => {
  it("splits the marks at the caret: what is typed next is plain", () => {
    const root = document.createElement("div");
    document.body.append(root);
    setOfHtml(root, '<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>abcd</strong></span></p>');
    const text = root.querySelector("strong")!.firstChild!;
    const sel = document.getSelection()!;
    const r = document.createRange();
    r.setStart(text, 2);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
    expect(clearAtCaret(root, sel)).toBe(true);
    expect(marksAt(root, sel.anchorNode)).toEqual(NO_MARKS);
    (sel.anchorNode as Text).insertData(sel.anchorOffset, "X");
    expect(editorValue(root)).toBe(
      '<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>ab</strong></span>X'
      + '<span class="m-editor-fs__l m-editor-fc__blue-1"><strong>cd</strong></span></p>');
    root.remove();
  });
  it("no mark at the caret: nothing to do", () => {
    const root = document.createElement("div");
    document.body.append(root);
    setOfHtml(root, "<p>plain</p>");
    const sel = document.getSelection()!;
    sel.removeAllRanges();
    const r = document.createRange();
    r.setStart(root.querySelector("p")!.firstChild!, 2);
    sel.addRange(r);
    expect(clearAtCaret(root, sel)).toBe(false);
    root.remove();
  });
});

describe("Default colour at a caret (the browser's foreColor placeholder)", () => {
  it.each<[string, string]>([
    ['<p><span class="m-editor-fc__blue-1">ab<font color="#000001">X</font></span></p>',
      '<p><span class="m-editor-fc__blue-1">ab</span><span class="m-editor-fc__default">X</span></p>'],
    ['<p><span style="color: rgb(0, 0, 1)">X</span></p>', '<p><span class="m-editor-fc__default">X</span></p>'],
  ])("%j", (html, want) => {
    const root = document.createElement("div");
    root.innerHTML = html;
    tidy(root);
    expect(editorValue(root)).toBe(want);
  });
});

describe("Codex C: paste keeps OF's formatting only", () => {
  it.each<[string, string, string | null]>([
    ["strong/em/OF span kept", '<p><strong>a</strong><em>b</em><span class="m-editor-fc__gray">c</span></p>',
      '<p><strong>a</strong><em>b</em><span class="m-editor-fc__gray">c</span></p>'],
    ["b/i become strong/em", "<b>a</b> <i>b</i>", "<p><strong>a</strong> <em>b</em></p>"],
    ["inline colour and size mapped to classes", '<span style="color: #00aff0; font-size: 20px">x</span>',
      '<p><span class="m-editor-fs__l m-editor-fc__blue-1">x</span></p>'],
    ["unknown colour / tags dropped, text kept", '<p><a href="x"><span style="color:red">x</span></a><img src=y></p>', null],
    ["word-processor junk", '<div><o:p></o:p><font face="Arial">plain</font></div>', null],
  ])("%s", (_n, html, want) => expect(pastedOfHtml(html, document)).toBe(want));
});

/** OF's own wire (measured: onlyfans.com web app, POST /api2/v2/chats/:id/messages, 2026-11-06; OF echoed it, 200):
 *  size + colour on a bold word. Every serializer writes this shape: span outermost, size class first. */
const OF_WIRE = '<p><span class="m-editor-fs__l m-editor-fc__blue-2"><strong>safgsfg</strong></span></p>';

describe("OF's wire format (HAR)", () => {
  it("sanitizeOfHtml keeps it byte for byte", () => expect(sanitizeOfHtml(OF_WIRE)).toBe(OF_WIRE));
  it("the editor loads and writes it back byte for byte", () => {
    const root = document.createElement("div");
    setOfHtml(root, OF_WIRE);
    expect(editorValue(root)).toBe(OF_WIRE);
  });
  it("legacy strong > span markup comes out in OF's shape", () =>
    expect(sanitizeOfHtml('<p><strong><span class="m-editor-fc__blue-2 m-editor-fs__l">safgsfg</span></strong></p>')).toBe(OF_WIRE));
  it("an outer mark stays open across runs that share it (ProseMirror)", () =>
    expect(sanitizeOfHtml('<p><span class="m-editor-fc__gray"><strong>a</strong>b<em>c</em></span>d</p>'))
      .toBe('<p><span class="m-editor-fc__gray"><strong>a</strong>b<em>c</em></span>d</p>'));
});
