/**
 * Growth > Sensitive words (page-parity ticket 14), with `@/lib/relay` mocked over a list of four words: two under
 * "A", one under "B", one under "Special symbol". Pins the letter tabs (`aria-selected`, one Tab stop, the arrow
 * keys), the word card's Edit / Delete on focus, "Total: N" over every word, and the Add dialog.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), post: vi.fn(), uploadFile: vi.fn() } };
});

import SensitiveWordsPage from "@/components/growth/SensitiveWordsPage";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;

const WORDS = ["apple", "avocado", "banana", "#tag"];

beforeEach(() => {
  get.mockResolvedValue({ words: WORDS });
  post.mockResolvedValue({ total: 1, success_count: 1, fail_count: 0, failed: [] });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderPage() {
  renderWithProviders(<SensitiveWordsPage />);
  await screen.findByRole("listitem", { name: "apple" });
}

describe("SensitiveWordsPage", () => {
  it("renders Infloww's 16 / 500 title", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Sensitive words" }).className).toContain("font-medium");
  });

  it("marks the open letter tab with aria-selected and keeps one Tab stop", async () => {
    await renderPage();
    const a = screen.getByRole("tab", { name: "A" });
    const b = screen.getByRole("tab", { name: "B" });
    expect(a).toHaveAttribute("aria-selected", "true");
    expect(a).toHaveAttribute("tabindex", "0");
    expect(b).toHaveAttribute("aria-selected", "false");
    expect(b).toHaveAttribute("tabindex", "-1");

    fireEvent.click(b);
    expect(b).toHaveAttribute("aria-selected", "true");
    expect(a).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("listitem", { name: "banana" })).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: "apple" })).toBeNull();
  });

  it("moves between letters with the arrow keys, wrapping at the ends", async () => {
    await renderPage();
    const a = screen.getByRole("tab", { name: "A" });
    a.focus();
    fireEvent.keyDown(a, { key: "ArrowRight" });
    const b = screen.getByRole("tab", { name: "B" });
    expect(b).toHaveAttribute("aria-selected", "true");
    expect(b).toHaveFocus();

    fireEvent.keyDown(b, { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("tab", { name: "A" }), { key: "ArrowLeft" });
    const special = screen.getByRole("tab", { name: "Special symbol" });
    expect(special).toHaveAttribute("aria-selected", "true");
    expect(special).toHaveFocus();
    expect(screen.getByRole("listitem", { name: "#tag" })).toBeInTheDocument();
  });

  it("shows Edit and Delete on a word card while focus is inside it", async () => {
    await renderPage();
    const card = screen.getByRole("listitem", { name: "apple" });
    expect(within(card).queryByRole("button", { name: "Edit" })).toBeNull();

    fireEvent.focus(card);
    const edit = within(card).getByRole("button", { name: "Edit" });
    expect(within(card).getByRole("button", { name: "Delete" })).toBeInTheDocument();

    // Focus moving from the card onto its own button keeps the overlay.
    fireEvent.blur(card, { relatedTarget: edit });
    expect(within(card).getByRole("button", { name: "Edit" })).toBeInTheDocument();

    fireEvent.blur(card, { relatedTarget: document.body });
    expect(within(card).queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("deletes the focused card's word", async () => {
    await renderPage();
    const card = screen.getByRole("listitem", { name: "avocado" });
    fireEvent.focus(card);
    fireEvent.click(within(card).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/admin/sensitive-words/delete", { words: ["avocado"] }));
  });

  it("counts every listed word in Total, not just the open tab's", async () => {
    await renderPage();
    expect(screen.getByText("Total: 4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "B" }));
    expect(screen.getByText("Total: 4")).toBeInTheDocument();
  });

  it("shows the empty state for a letter with no words", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Z" }));
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("opens the Add dialog and saves the typed word", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Add Sensitive Word" }));
    const dialog = screen.getByRole("dialog", { name: "Add Sensitive Word" });
    fireEvent.change(within(dialog).getByLabelText("Sensitive word 1"), { target: { value: "cherry" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/admin/sensitive-words/add", { words: ["cherry"] }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("refuses an empty row in the Add dialog", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Add Sensitive Word" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Please enter a sensitive word")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });
});
