/**
 * OfRichText (an OF body as the fan sees it) and OfRichTextEditor (the script editor's Text field) in jsdom: the
 * renderer builds OF's marks as elements (never raw HTML), plain bodies render as the plain text they always did;
 * the editor loads plain and markup values, emits plain text until there is formatting, never reloads its own echo,
 * and inserts at the caret.
 */
import { createRef } from "react";
import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OfRichText } from "./OfRichText";
import { OfRichTextEditor, type OfRichTextEditorHandle } from "@/components/ui/OfRichTextEditor";

describe("OfRichText", () => {
  const rows: [string, string, string, string | null][] = [
    // (name, raw, text shown, inner HTML of the rich root or null for the plain path)
    ["plain text", "hi\nthere", "hi\nthere", null],
    ["plain text with an angle-bracket code, as written", "code <VIP20>", "code <VIP20>", null],
    ["plain text with an entity, as written", "a &amp; b", "a &amp; b", null],
    ["unformatted markup", "<p>a &amp; b</p><p>c</p>", "a & b\nc", null],
    ["bold blue large", '<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>Hey</strong></span> you</p>',
      "Hey you", '<span class="m-editor-fs__l m-editor-fc__blue-1"><strong>Hey</strong></span> you'],
    ["folded blank line", "<p><em>a</em><br><br>b</p>", "a\n\nb", "<em>a</em>\n\nb"],
    ["foreign markup never rendered", '<p><strong>x</strong><img src=x onerror="alert(1)"><script>alert(2)</script></p>',
      "x", "<strong>x</strong>"],
  ];
  it.each(rows)("%s", (_n, raw, text, inner) => {
    const { container } = render(<OfRichText raw={raw} />);
    const root = container.firstElementChild as HTMLElement;
    expect(root.textContent).toBe(text);
    expect(container.querySelector("img, script")).toBeNull();
    if (inner == null) expect(root.hasAttribute("data-of-rich")).toBe(false);
    else {
      expect(root.getAttribute("data-of-rich")).toBe("");
      expect(root.className).toContain("of-rt");
      expect(root.innerHTML).toBe(inner);
    }
  });
});

const box = (c: HTMLElement) => c.querySelector<HTMLElement>("[role=textbox]")!;

describe("OfRichTextEditor", () => {
  it("loads plain text as paragraphs and emits plain text for an unformatted edit", () => {
    const onChange = vi.fn();
    const { container } = render(<OfRichTextEditor value={"a\nb"} onChange={onChange} placeholder="Enter your message..." maxLength={10} />);
    const el = box(container);
    expect(el.innerHTML).toBe("<p>a</p><p>b</p>");
    expect(el.getAttribute("placeholder")).toBe("Enter your message...");
    el.querySelector("p")!.textContent = "abc";
    fireEvent.input(el);
    expect(onChange).toHaveBeenLastCalledWith("abc\nb");
  });

  it("emits OF markup once the text has formatting, and does not reload its own echo", () => {
    const onChange = vi.fn();
    const { container, rerender } = render(<OfRichTextEditor value="hey" onChange={onChange} />);
    const el = box(container);
    el.innerHTML = "<p><b>hey</b></p>"; // what the browser's bold leaves
    fireEvent.input(el);
    expect(onChange).toHaveBeenLastCalledWith("<p><strong>hey</strong></p>");
    const node = el.querySelector("strong");
    rerender(<OfRichTextEditor value="<p><strong>hey</strong></p>" onChange={onChange} />);
    expect(el.querySelector("strong")).toBe(node); // same node: the caret stays where it was
  });

  it("loads a stored formatted script through the allow-list and lights its marks in the toolbar", () => {
    const { container } = render(
      <OfRichTextEditor value={'<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>x</strong></span></p>'} onChange={() => {}} />);
    const el = box(container);
    expect(el.innerHTML).toBe('<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>x</strong></span></p>');
    const sel = document.getSelection()!;
    const r = document.createRange();
    r.setStart(el.querySelector("strong")!.firstChild!, 1);
    sel.removeAllRanges();
    sel.addRange(r);
    act(() => { document.dispatchEvent(new Event("selectionchange")); });
    expect(container.querySelector("[aria-label=Bold]")!.getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector("[title='Text size']")!.textContent).toContain("Large");
  });

  it("inserts at the caret through its handle (the emoji row)", () => {
    const onChange = vi.fn();
    const ref = createRef<OfRichTextEditorHandle>();
    const { container } = render(<OfRichTextEditor ref={ref} value="ab" onChange={onChange} />);
    const el = box(container);
    const sel = document.getSelection()!;
    const r = document.createRange();
    r.setStart(el.querySelector("p")!.firstChild!, 1);
    sel.removeAllRanges();
    sel.addRange(r);
    act(() => { document.dispatchEvent(new Event("selectionchange")); });
    act(() => ref.current!.insert("💖"));
    expect(onChange).toHaveBeenLastCalledWith("a💖b");
  });

  it("keeps typed leading/trailing empty lines (the value is what was typed, untrimmed)", () => {
    const onChange = vi.fn();
    const { container } = render(<OfRichTextEditor value={"\nhi\n"} onChange={onChange} />);
    const el = box(container);
    el.querySelectorAll("p")[1].textContent = "hey";
    fireEvent.input(el);
    expect(onChange).toHaveBeenLastCalledWith("\nhey\n");
  });

  it("a drop goes in as plain text, cut to the room left", () => {
    const exec = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
    try {
      const { container } = render(<OfRichTextEditor value="ab" onChange={() => {}} maxLength={5} />);
      const drop = new Event("drop", { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown };
      drop.dataTransfer = { getData: (t: string) => (t === "text/plain" ? "<b>xyz</b>" : "<b>html</b>") };
      box(container).dispatchEvent(drop);
      expect(drop.defaultPrevented).toBe(true);
      expect(exec).toHaveBeenLastCalledWith("insertText", false, "<b>");
    } finally {
      delete (document as unknown as Record<string, unknown>).execCommand;
    }
  });

  it("at the limit, an insert that replaces the selection still fits", () => {
    const onChange = vi.fn();
    const ref = createRef<OfRichTextEditorHandle>();
    const { container } = render(<OfRichTextEditor ref={ref} value="abcde" onChange={onChange} maxLength={5} />);
    const t = box(container).querySelector("p")!.firstChild!;
    const sel = document.getSelection()!;
    const r = document.createRange();
    r.setStart(t, 2);
    r.setEnd(t, 4);
    sel.removeAllRanges();
    sel.addRange(r);
    act(() => { document.dispatchEvent(new Event("selectionchange")); });
    act(() => ref.current!.insert("XY"));
    expect(onChange).toHaveBeenLastCalledWith("abXYe");
    act(() => ref.current!.insert("Z")); // collapsed caret, full: refused
    expect(onChange).toHaveBeenLastCalledWith("abXYe");
  });
});
