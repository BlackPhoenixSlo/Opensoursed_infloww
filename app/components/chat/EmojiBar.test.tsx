import { useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { EMOJI_LIST, EmojiPickerButton, EmojiQuickRow, QUICK_EMOJIS, insertAtCursor } from "./EmojiBar";
import { CATEGORIES } from "./emojiData";

afterEach(() => window.localStorage.clear());

/** A composer: textarea + quick row + picker, both inserting at the caret. */
function Harness({ initial = "", messagesPro }: { initial?: string; messagesPro?: boolean }) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const insert = (e: string) => { if (ref.current) insertAtCursor(ref.current, value, e, setValue); };
  return (
    <>
      <textarea aria-label="draft" ref={ref} value={value} onChange={(e) => setValue(e.target.value)} />
      <div data-testid="quick"><EmojiQuickRow onInsert={insert} /></div>
      <EmojiPickerButton onInsert={insert} messagesPro={messagesPro} />
    </>
  );
}

const draft = () => screen.getByLabelText("draft") as HTMLTextAreaElement;
const openPicker = () => fireEvent.click(screen.getByLabelText("Emoji picker"));
const search = () => screen.getByPlaceholderText("Search emoji…");
/** The open picker's emoji-grid buttons: not a titled tab, the trigger or a quick-row button. */
const gridButtons = () => screen.getAllByRole("button")
  .filter((b) => !b.title && b.getAttribute("aria-label") !== "Emoji picker" && !screen.getByTestId("quick").contains(b));
/** Both quick rows' emojis: desktop (8 slots), then phone (its first 5). */
const quickButtons = () => within(screen.getByTestId("quick")).getAllByRole("button").map((b) => b.textContent);

describe("EmojiBar", () => {
  it("re-exports the emoji data", () => {
    expect(QUICK_EMOJIS[0]).toBe("❤️");
    expect(EMOJI_LIST.length).toBe(CATEGORIES.reduce((n, c) => n + c.items.length, 0));
  });

  it("quick row renders the defaults with no recents", () => {
    render(<Harness />);
    expect(quickButtons()).toEqual([...QUICK_EMOJIS, ...QUICK_EMOJIS.slice(0, 5)]);
  });

  it("search filters the picker by keyword", () => {
    render(<Harness />);
    openPicker();
    fireEvent.change(search(), { target: { value: "eggplant" } });
    expect(screen.getAllByRole("button", { name: "🍆" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "🐶" })).toBeNull();
    fireEvent.change(search(), { target: { value: "zzzzqq" } });
    expect(screen.getByText(/No emoji match/)).toBeInTheDocument();
  });

  it("a pick replaces the selection at the caret, closes, and leads the quick row", async () => {
    render(<Harness initial="hello world" />);
    draft().setSelectionRange(0, 5); // "hello"
    openPicker();
    fireEvent.change(search(), { target: { value: "puppy" } });
    fireEvent.click(screen.getByRole("button", { name: "🐶" }));
    expect(draft().value).toBe("🐶 world");
    await waitFor(() => expect(draft().selectionStart).toBe("🐶".length));
    expect(draft().selectionEnd).toBe("🐶".length);
    expect(screen.queryByPlaceholderText("Search emoji…")).toBeNull();
    const quick = quickButtons();
    expect(quick).toHaveLength(13);
    expect([quick[0], quick[8]]).toEqual(["🐶", "🐶"]);
  });

  it("reopening keeps the tab and clears the search; recents tab shows the pick", () => {
    render(<Harness />);
    openPicker();
    fireEvent.click(screen.getByTitle("animals"));
    fireEvent.change(search(), { target: { value: "cat" } });
    openPicker(); // close
    openPicker();
    expect(search()).toHaveValue("");
    expect(screen.getByTitle("animals")).toHaveClass("bg-bg-elev-1");
    fireEvent.click(gridButtons().find((b) => b.textContent === "🐶")!);
    openPicker();
    fireEvent.click(screen.getByTitle("Recent"));
    expect(gridButtons().map((b) => b.textContent)).toEqual(["🐶"]);
  });

  it("Messages Pro opens on Favourites when some are saved", () => {
    window.localStorage.setItem("chatterly:emoji_favourites", JSON.stringify(["💋", "🔥"]));
    render(<Harness messagesPro />);
    openPicker();
    expect(screen.getByLabelText("Favourites")).toHaveAttribute("aria-pressed", "true");
  });

  it("outside Messages Pro there is no Favourites tab", () => {
    window.localStorage.setItem("chatterly:emoji_favourites", JSON.stringify(["💋"]));
    render(<Harness />);
    openPicker();
    expect(screen.queryByLabelText("Favourites")).toBeNull();
  });
});
