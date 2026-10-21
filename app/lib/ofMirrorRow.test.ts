import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { applyRow, basePage, parseRow, ROW_TARGETS } from "./ofMirrorRow";

const page = (p: string) => readFileSync(resolve(__dirname, `../public/of-mirror/pages/${p}.html`), "utf8");
const load = (p: string) => {
  document.documentElement.innerHTML = page(p);
  return document;
};
const shown = (doc: Document, p: string) => [...doc.querySelectorAll(ROW_TARGETS[basePage(p)].name)].map((e) => e.textContent?.trim());
/** The names of the rows marked current. */
const current = (doc: Document, p: string) => {
  const c = ROW_TARGETS[basePage(p)].current!;
  return [...new Set([...doc.querySelectorAll(c.rows)].filter((r) => r.classList.contains(c.cls[0])).map((r) => r.querySelector(c.name)?.textContent?.trim()))];
};
/** The names of the rows, other than the current one. */
const others = (doc: Document, p: string) => {
  const c = ROW_TARGETS[basePage(p)].current!;
  return [...doc.querySelectorAll(c.rows)].filter((r) => !r.classList.contains(c.cls[0])).map((r) => r.querySelector(c.name)?.textContent?.trim() ?? "");
};

describe("parseRow", () => {
  it("splits name and handle", () => {
    expect(parseRow("Fan 3|fan3")).toEqual({ name: "Fan 3", handle: "fan3" });
    expect(parseRow("List 26")).toEqual({ name: "List 26" });
    expect(parseRow("")).toBeNull();
    expect(parseRow(null)).toBeNull();
  });
});

describe("applyRow", () => {
  it.each([...Object.keys(ROW_TARGETS), "messages/chat/state-price"])("%s: shows the row's name instead of the example's, and the example again without one", (p) => {
    const doc = load(p);
    const example = shown(doc, p);
    const title = doc.title;
    expect(example.length).toBeGreaterThan(0);
    applyRow(doc, p, { name: "Row Name", handle: "rowhandle" });
    expect(shown(doc, p).every((t) => t === "Row Name")).toBe(true);
    expect(doc.title).toBe(title.replace(/[^:›]+$/, " Row Name"));
    applyRow(doc, p, null);
    expect(shown(doc, p)).toEqual(example);
    expect(doc.title).toBe(title);
  });

  // The chat list and the user lists keep no example rows (the generator drops them; ofMirrorData draws the real ones).
  it.each(Object.keys(ROW_TARGETS).filter((p) => p !== "messages/chat" && p !== "collections/user-lists/list"))("%s: moves the current-row mark to the row named in the query, and back", (p) => {
    const doc = load(p);
    const own = current(doc, p);
    expect(own).toHaveLength(1);
    const other = others(doc, p).find((n) => n && n !== own[0])!;
    applyRow(doc, p, { name: other });
    expect(current(doc, p)).toEqual([other]);
    applyRow(doc, p, { name: "No Such Row" }); // no match: the example's row stays current
    expect(current(doc, p)).toEqual(own);
    applyRow(doc, p, { name: other });
    applyRow(doc, p, null);
    expect(current(doc, p)).toEqual(own);
    const aria = [...doc.querySelectorAll(`${ROW_TARGETS[p].current!.rows}[aria-current]`)].length;
    expect(aria).toBe(ROW_TARGETS[p].current!.aria ? 1 : 0);
  });

  it("replaces the chat partner's @handle mentions, not other fans'", () => {
    const doc = load("messages/chat");
    const fan = doc.querySelector(ROW_TARGETS["messages/chat"].name)!.closest("[data-fan]")!.getAttribute("data-fan");
    const mentions = () => [...doc.querySelectorAll(".b-chat__message__text-holder a[data-fan]")].map((a) => [a.getAttribute("data-fan"), a.textContent]);
    const before = mentions();
    expect(before.some(([f, t]) => f === fan && t?.startsWith("@"))).toBe(true);
    applyRow(doc, "messages/chat", { name: "Row Name", handle: "rowhandle" });
    for (const [i, [f, t]] of mentions().entries()) expect(t).toBe(f === fan && before[i][1]?.startsWith("@") ? "@rowhandle" : before[i][1]);
    applyRow(doc, "messages/chat", null);
    expect(mentions()).toEqual(before);
  });

  it("keeps the query on links to the page itself and its state/modal pages", () => {
    const doc = load("messages/chat/state-price");
    const hrefs = () => [...doc.querySelectorAll("a[href^='/of-manager/messages/chat']")].map((a) => a.getAttribute("href")!);
    const before = hrefs();
    applyRow(doc, "messages/chat/state-price", { name: "Fan 3", handle: "fan3" });
    const after = hrefs();
    for (const [i, h] of before.entries()) {
      const carries = h === "/of-manager/messages/chat" || /^\/of-manager\/messages\/chat\/(?:state|modal)-/.test(h);
      expect(after[i]).toBe(carries ? `${h}?row=Fan%203|fan3` : h);
    }
    expect(after).toContain("/of-manager/messages/chat?row=Fan%203|fan3"); // the dialog's way back
    applyRow(doc, "messages/chat/state-price", null);
    expect(hrefs()).toEqual(before);
  });

  it("leaves other pages alone", () => {
    const doc = load("messages/index");
    const html = doc.documentElement.innerHTML;
    applyRow(doc, "messages/index", { name: "Row Name" });
    expect(doc.documentElement.innerHTML).toBe(html);
  });
});

describe("row links", () => {
  it("each row on the list pages links to its target page with its own ?row=", () => {
    // The vault and the user lists keep no example row (ofMirrorData lists the Creator's, each opening ?list=<id>).
    expect(load("vault/index").querySelectorAll("a[href^='/of-manager/vault/list?row=']")).toHaveLength(0);
    for (const p of ["collections/index", "collections/user-lists/list"])
      expect(load(p).querySelectorAll("a[href^='/of-manager/collections/user-lists/list?row=']"), p).toHaveLength(0);
  });
});
