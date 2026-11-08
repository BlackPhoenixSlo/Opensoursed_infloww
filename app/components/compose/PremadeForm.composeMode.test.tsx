/**
 * PremadeForm, the ready-made rule composer dialog (W5b-2).
 *
 * A rule editor embeds PremadeForm to build an `auto_posts` / `mass_premade`
 * rule payload, passing `onComposePayload` + `accountId`. The dialog
 * renders "Use in rule" (no enqueue button, no all-models switch) and hands the
 * exact `{posts|messages:[…]}` payload back via the callback. (It has no send
 * path of its own: it imports no relay write.)
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { PremadeForm } from "@/components/compose/PremadeForm";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(async () => []) } }));
vi.mock("@/contexts/EmployeeContext", () => ({
  useEmployee: () => ({ current: { id: 1 } }),
}));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [{ id: "acct1", nickname: "A", color: "#fff" }],
  usePlatformAccounts: () => [{ id: "acct1", nickname: "A", color: "#fff" }],
}));
vi.mock("@/hooks/useAllModelsInclude", () => ({
  useAllModelsInclude: () => ({ isIncluded: () => true, toggle: vi.fn() }),
}));
vi.mock("@/hooks/useVaultMedia", () => ({
  useVaultLists: () => ({ data: { list: [] }, isLoading: false }),
}));
// The vault picker's last props (it renders nothing): which pool it opens for, and its confirm.
type PickerProps = {
  open: boolean; initialSelectedIds: number[]; onClose: () => void; onConfirm: (p: { id: number }[]) => void;
};
const picker = vi.hoisted(() => ({ all: [] as PickerProps[] }));
vi.mock("@/components/chat/VaultPicker", () => ({
  VaultPicker: (p: PickerProps) => { picker.all.push(p); return null; },
}));
const lastPicker = () => picker.all[picker.all.length - 1];

afterEach(() => cleanup());

describe("PremadeForm return-payload mode", () => {
  it("auto_posts: hands back {posts:[…]}", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <PremadeForm
        kind="auto_posts"
        accountId="acct1" title="Compose" onClose={vi.fn()}
        onComposePayload={onComposePayload}
      />,
    );

    // No all-models switch + no enqueue button in return mode.
    expect(screen.queryByText(/from ALL models/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /enqueue/i })).toBeNull();

    fireEvent.change(screen.getByPlaceholderText(/post caption/i), {
      target: { value: "hello world" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));

    expect(onComposePayload).toHaveBeenCalledTimes(1);
    expect(onComposePayload).toHaveBeenCalledWith({ posts: [{ text: "hello world" }] });
  });

  it("auto_posts: a PPV price rides into the {posts:[…]} payload", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <PremadeForm
        kind="auto_posts"
        accountId="acct1" title="Compose" onClose={vi.fn()}
        onComposePayload={onComposePayload}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/post caption/i), {
      target: { value: "locked pic" },
    });
    // The auto_posts-only price field (dollars) → emitted only when >0.
    fireEvent.change(screen.getByPlaceholderText(/0 \(free\)/i), {
      target: { value: "19.99" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));

    expect(onComposePayload).toHaveBeenCalledWith({
      posts: [{ text: "locked pic", price: 19.99 }],
    });
  });

  it("mass_premade: hands back {messages:[…]}, the default audience and online-only included", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <PremadeForm
        kind="mass_premade"
        accountId="acct1" title="Compose" onClose={vi.fn()}
        onComposePayload={onComposePayload}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), {
      target: { value: "premade promo" },
    });
    // Price parity with auto_posts: a PPV broadcast rides `price` too
    // (mass_premade → send_mass_message both read it).
    fireEvent.change(screen.getByPlaceholderText(/0 \(free\)/i), {
      target: { value: "9.99" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));

    expect(onComposePayload).toHaveBeenCalledTimes(1);
    expect(onComposePayload).toHaveBeenCalledWith({
      messages: [{ text: "premade promo", price: 9.99, online_only: true, user_lists: ["fans", "following"] }],
    });
  });

  it("mass_premade: a system chip is include-only (OF drops a built-in name in excludedLists)", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(<PremadeForm kind="mass_premade" accountId="acct1" title="Compose" onClose={vi.fn()} onComposePayload={onComposePayload} />);
    fireEvent.change(screen.getByPlaceholderText(/broadcast text/i), { target: { value: "x" } });
    const fans = screen.getByRole("button", { name: /All fans/ });
    fireEvent.click(fans); // included → off
    expect(fans).toHaveTextContent("OF built-in");
    fireEvent.click(fans); // off → included, never "exclude"
    fireEvent.click(fans);
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledWith({ messages: [{ text: "x", online_only: true, user_lists: ["following"] }] });
  });

  it("one vault picker fills the image pool or the preview pool it was opened for", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(<PremadeForm kind="auto_posts" accountId="acct1" title="Compose" onClose={vi.fn()} onComposePayload={onComposePayload} />);
    fireEvent.change(screen.getByPlaceholderText(/0 \(free\)/i), { target: { value: "5" } });
    picker.all = [];
    fireEvent.click(screen.getByRole("button", { name: "Pick image pool" }));
    expect(lastPicker().open).toBe(true);
    act(() => lastPicker().onConfirm([{ id: 1 }, { id: 2 }]));
    expect(lastPicker().open).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Pick preview pool" }));
    expect(lastPicker().initialSelectedIds).toEqual([]);
    act(() => lastPicker().onConfirm([{ id: 3 }]));
    fireEvent.click(screen.getByRole("button", { name: "2 in pool" }));
    expect(lastPicker().initialSelectedIds).toEqual([1, 2]);
    act(() => lastPicker().onClose());
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledWith({
      posts: [{ media_files: [1, 2], price: 5, preview_media_files: [3] }],
    });
  });

  it("does nothing (no callback) when there's no content", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <PremadeForm
        kind="auto_posts"
        accountId="acct1" title="Compose" onClose={vi.fn()}
        onComposePayload={onComposePayload}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).not.toHaveBeenCalled();
  });

  it("a saved folder that is gone (none fetched) still shows and clears", () => {
    const onComposePayload = vi.fn();
    renderWithProviders(
      <PremadeForm
        kind="auto_posts"
        accountId="acct1" title="Compose" onClose={vi.fn()}
        onComposePayload={onComposePayload}
        initialPayload={{ posts: [{ text: "hi", media_folder_id: 77 }] }}
      />,
    );
    const folder = screen.getAllByLabelText("Folder pool")[0];
    expect(folder).toBeEnabled();
    expect(folder).toHaveTextContent("Missing folder #77");
    fireEvent.click(folder);
    fireEvent.click(screen.getByRole("option", { name: "No photo folders" }));
    expect(folder).toHaveTextContent("No photo folders");
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledWith({ posts: [{ text: "hi" }] });
  });

  // The text-variant pool: typed, added and imported variants land in `texts` in order (dupes skipped).
  it.each([
    ["auto_posts", /post caption/i, "posts"],
    ["mass_premade", /broadcast text/i, "messages"],
  ] as const)("%s: the variant pool rides as texts", (kind, ph, key) => {
    const onComposePayload = vi.fn();
    const { container } = renderWithProviders(<PremadeForm kind={kind} accountId="acct1" title="Compose" onClose={vi.fn()} onComposePayload={onComposePayload} />);
    const first = screen.getByPlaceholderText(ph);
    fireEvent.change(first, { target: { value: " a " } });
    fireEvent.click(screen.getByRole("button", { name: /^Add variant/ }));
    const boxes = [...container.querySelectorAll("textarea")];
    fireEvent.change(boxes[boxes.indexOf(first as HTMLTextAreaElement) + 1], { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: "Import captions" }));
    fireEvent.change(screen.getByLabelText("Paste captions"), { target: { value: "c\nb" } });
    fireEvent.click(screen.getByRole("button", { name: "Add pasted" }));
    fireEvent.click(screen.getByRole("button", { name: /use in rule/i }));
    expect(onComposePayload).toHaveBeenCalledTimes(1);
    expect(onComposePayload.mock.calls[0][0][key][0].texts).toEqual(["a", "b", "c"]);
  });
});

describe("the composer dialog — Escape never drops an edited draft", () => {
  const escape = () => fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  it("clean: Escape closes", () => {
    const onClose = vi.fn();
    renderWithProviders(<PremadeForm kind="auto_posts" accountId="acct1" title="Compose" onClose={onClose} onComposePayload={vi.fn()} />);
    escape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
  it("dirty: Escape does nothing", () => {
    const onClose = vi.fn();
    renderWithProviders(<PremadeForm kind="auto_posts" accountId="acct1" title="Compose" onClose={onClose} onComposePayload={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/post caption/i), { target: { value: "hello" } });
    escape();
    expect(onClose).not.toHaveBeenCalled();
  });
  it("a repost-cycle edit holds Escape too, even reverted (touched until it closes)", () => {
    const onClose = vi.fn();
    renderWithProviders(<PremadeForm kind="auto_posts" accountId="acct1" title="Compose" onClose={onClose} onComposePayload={vi.fn()} />);
    const hours = screen.getByLabelText("Repost whole list after");
    fireEvent.change(hours, { target: { value: "24" } });
    fireEvent.change(hours, { target: { value: "" } });
    escape();
    expect(onClose).not.toHaveBeenCalled();
  });
  it("opening and cancelling the vault picker is no edit: Escape still closes", () => {
    const onClose = vi.fn();
    renderWithProviders(<PremadeForm kind="auto_posts" accountId="acct1" title="Compose" onClose={onClose} onComposePayload={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Pick image pool" }));
    act(() => lastPicker().onClose());
    escape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
