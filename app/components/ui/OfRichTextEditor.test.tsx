/**
 * OfRichTextEditor and an IME (item 6): mid-composition input never emits (normalizing would move the IME's text
 * under it); compositionend emits once with the composed text. The host's toolbar prop hides the formatting row.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OfRichTextEditor } from "./OfRichTextEditor";

afterEach(cleanup);

const box = () => screen.getByRole("textbox");

describe("OfRichTextEditor", () => {
  it.each<[string, boolean, number]>([
    ["mid-composition input: no emit", true, 0],
    ["ordinary input: emits", false, 1],
  ])("%s", (_n, isComposing, calls) => {
    const onChange = vi.fn();
    render(<OfRichTextEditor value="" onChange={onChange} aria-label="t" />);
    box().querySelector("p")!.textContent = "ni";
    fireEvent.input(box(), { isComposing });
    expect(onChange).toHaveBeenCalledTimes(calls);
  });

  it("compositionend emits the composed text once", () => {
    const onChange = vi.fn();
    render(<OfRichTextEditor value="" onChange={onChange} aria-label="t" />);
    box().querySelector("p")!.textContent = "你好";
    fireEvent.input(box(), { isComposing: true });
    fireEvent.compositionEnd(box());
    fireEvent.input(box(), { isComposing: false }); // the browser's trailing input: same value, no second emit
    expect(onChange.mock.calls).toEqual([["你好"]]);
  });

  it("Shift+Enter makes a new paragraph (never a literal newline in one); the host's handled Enter is left alone", () => {
    const exec = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
    const onKeyDown = vi.fn((e: { key: string; shiftKey: boolean; preventDefault(): void }) => {
      if (e.key === "Enter" && !e.shiftKey) e.preventDefault(); // the chat Composer: Enter sends
    });
    render(<OfRichTextEditor value="" onChange={() => {}} aria-label="t" onKeyDown={onKeyDown} />);
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(exec.mock.calls).toEqual([["insertParagraph", false, undefined]]);
    expect(onKeyDown).toHaveBeenCalledTimes(2);
    delete (document as { execCommand?: unknown }).execCommand;
  });

  it.each<[boolean, boolean]>([[true, true], [false, false]])("toolbar=%s draws the formatting row: %s", (toolbar, shown) => {
    render(<OfRichTextEditor value="" onChange={() => {}} aria-label="t" toolbar={toolbar} />);
    expect(!!screen.queryByRole("toolbar", { name: "Text formatting" })).toBe(shown);
  });
});
