import { describe, expect, it } from "vitest";
import { undoList, type UndoOptions } from "./ofMirrorUndo";

// The three lists in use: ofMirrorData's, ofMirrorMoney's, ofMirrorStatsDom's.
const DATA: UndoOptions = { attrMode: "single", classUndo: "snapshot", skipEqualText: false };
const MONEY: UndoOptions = { attrMode: "all-in-order", classUndo: "snapshot", skipEqualText: true };
const STATS: UndoOptions = { attrMode: "single", classUndo: "toggle", skipEqualText: true };

const MARKUP = `<div id="a" class="box on" data-x="1" title="t"><span class="n">5</span><b>x</b></div>`;
const page = (html = MARKUP) => {
  document.body.innerHTML = html;
  return document.body.firstElementChild!;
};

describe("undoList", () => {
  it.each([
    ["data", DATA],
    ["money", MONEY],
    ["stats", STATS],
  ])("%s: a mix of changes, restored, is the markup byte for byte", (_, opts) => {
    const l = undoList(opts);
    const root = page();
    const span = root.querySelector("span")!;
    l.setText(document, span, "7");
    l.setText(document, span, "8");
    l.setClass(document, span, "hot", true);
    l.setClass(document, root, "lit", true); // turned on: every classUndo restores it (off: "toggle" reorders, below)
    l.setAttr(document, root, "title", "u");
    l.setAttr(document, root, "data-new", "y");
    l.setAttr(document, root.querySelector("b"), "hidden", "");
    l.setText(document, null, "no-op");
    l.setAttr(document, undefined, "x", "no-op");
    expect(root.outerHTML).not.toBe(MARKUP);
    l.restore(document);
    expect(root.outerHTML).toBe(MARKUP);
  });

  // Removing an attribute that is not last, then restoring: "single" re-adds it last, "all-in-order" in its place.
  it.each([
    ["single", DATA, `<div id="a" class="box on" title="t" data-x="1"><span class="n">5</span><b>x</b></div>`],
    ["all-in-order", MONEY, MARKUP],
  ])("attrMode %s: a removed attribute comes back where?", (_, opts, want) => {
    const l = undoList(opts);
    const root = page();
    l.setAttr(document, root, "data-x", null);
    expect(root.hasAttribute("data-x")).toBe(false);
    l.restore(document);
    expect(root.outerHTML).toBe(want);
  });

  // A class turned off and back: "toggle" appends it, "snapshot" puts the class attribute back as it was.
  it.each([
    ["toggle", STATS, `<p class="on box"></p>`, `<p></p>`, `<p class=""></p>`],
    ["snapshot", DATA, `<p class="box on"></p>`, `<p></p>`, `<p></p>`],
  ])("classUndo %s", (_, opts, offBack, bare, bareBack) => {
    const l = undoList(opts);
    const p = page(`<p class="box on"></p>`);
    l.setClass(document, p, "box", false);
    l.restore(document);
    expect(p.outerHTML).toBe(offBack);
    const q = page(bare);
    l.setClass(document, q, "x", true);
    expect(q.outerHTML).toBe(`<p class="x"></p>`);
    l.restore(document);
    expect(q.outerHTML).toBe(bareBack);
  });

  it.each([
    ["skip", MONEY, 0],
    ["no skip", DATA, 1],
  ])("skipEqualText (%s): the same text registers %i undo", (_, opts, n) => {
    const l = undoList(opts);
    const root = page();
    const span = root.querySelector("span")!;
    l.setText(document, span, "5");
    span.textContent = "changed elsewhere";
    l.restore(document);
    expect(span.textContent).toBe(n ? "5" : "changed elsewhere");
  });

  it("own: its changes survive restore, its undo reverts them; tracked changes after it go to the page", () => {
    const l = undoList(DATA);
    const root = page();
    const span = root.querySelector("span")!;
    const undo = l.own(() => {
      l.setText(document, span, "mine");
      l.setAttr(document, root, "title", "mine");
    });
    l.setClass(document, span, "page", true);
    l.restore(document);
    expect(span.textContent).toBe("mine");
    expect(root.getAttribute("title")).toBe("mine");
    expect(span.className).toBe("n");
    undo();
    expect(root.outerHTML).toBe(MARKUP);
  });

  it("own: a throwing apply still ends own (later changes go to the page)", () => {
    const l = undoList(DATA);
    const root = page();
    expect(() => l.own(() => { throw new Error("x"); })).toThrow("x");
    l.setAttr(document, root, "title", "u");
    l.restore(document);
    expect(root.outerHTML).toBe(MARKUP);
  });

  it("own nested: each undo reverts only its own changes, restore neither", () => {
    const l = undoList(DATA);
    const root = page();
    const span = root.querySelector("span")!;
    let inner = () => {};
    const outer = l.own(() => {
      l.setText(document, span, "outer");
      inner = l.own(() => l.setAttr(document, root, "title", "inner"));
      l.setClass(document, span, "after", true); // back on outer's list once inner ends
    });
    l.restore(document);
    expect(root.outerHTML).toBe(`<div id="a" class="box on" data-x="1" title="inner"><span class="n after">outer</span><b>x</b></div>`);
    outer();
    expect(root.outerHTML).toBe(`<div id="a" class="box on" data-x="1" title="inner"><span class="n">5</span><b>x</b></div>`);
    inner();
    expect(root.outerHTML).toBe(MARKUP);
  });

  it("own on list A leaves list B's tracking to B's page list", () => {
    const a = undoList(DATA);
    const b = undoList(MONEY);
    const root = page();
    const undoA = a.own(() => b.setAttr(document, root, "title", "b"));
    undoA();
    expect(root.getAttribute("title")).toBe("b");
    b.restore(document);
    expect(root.outerHTML).toBe(MARKUP);
  });

  it("swapIn: the first matching text node only, undone by restore", () => {
    const l = undoList(STATS);
    const root = page(`<p>Min $20 <b>then $20</b></p>`);
    l.swapIn(document, root, /\$\d+/, "$50");
    l.swapIn(document, root, /nothing/, "x");
    l.swapIn(document, null, /\$\d+/, "x");
    expect(root.outerHTML).toBe(`<p>Min $50 <b>then $20</b></p>`);
    l.restore(document);
    expect(root.outerHTML).toBe(`<p>Min $20 <b>then $20</b></p>`);
  });

  it("two lists on one page restore independently", () => {
    const a = undoList(DATA);
    const b = undoList(MONEY);
    const root = page();
    const span = root.querySelector("span")!;
    a.setText(document, span, "a");
    b.setAttr(document, root, "title", "b");
    a.restore(document);
    expect(span.textContent).toBe("5");
    expect(root.getAttribute("title")).toBe("b");
    b.restore(document);
    expect(root.outerHTML).toBe(MARKUP);
  });
});
