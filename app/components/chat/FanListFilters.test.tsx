/**
 * FanListFilters — the Fan List's filter row, chip row and folder row, tested at their
 * props, which are the module's public interface
 * (docs/spec/phase-02-fan-list-pane.md, Testing Decisions). The module is
 * stateless: each case renders it at fixed props and reads the callbacks.
 * Later filter tickets add their cases here.
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test-utils";
import { FanListFilters } from "./FanListFilters";

function renderFilters(props: Partial<Parameters<typeof FanListFilters>[0]> = {}) {
  const callbacks = {
    onActiveChange: vi.fn(), onOpenFolderPicker: vi.fn(), onRefresh: vi.fn(), onMarkAllRead: vi.fn(),
    onKeepDrawerOpenChange: vi.fn(), onBlurModeChange: vi.fn(), onCompactMediaChange: vi.fn(), onSortModeChange: vi.fn(),
    onOpenSplitInbox: vi.fn(), onGroupChange: vi.fn(), onSelectChats: vi.fn(),
  };
  renderWithProviders(
    <FanListFilters
      active={{ kind: "builtin", key: "all" }}
      unreadCount={0}
      activeCount={0}
      oweReplyCount={0}
      pinnedFolders={[]}
      hasLists={false}
      showInboxSelector
      groupCount={1}
      group={null}
      fetching={false}
      markingAll={false}
      hasUnread
      keepDrawerOpen
      blurMode="off"
      compactMedia
      sortMode="recent"
      tipsEnabled={false}
      {...callbacks}
      {...props}
    />,
  );
  return callbacks;
}

afterEach(cleanup);

const filterRow = () => screen.getByRole("group", { name: "Inbox, settings and sort" });

describe("FanListFilters", () => {
  it("renders the filter row's \"All inboxes\" selector, gear, sort control and refresh icon in that order, ahead of the chips", () => {
    renderFilters();

    expect(within(filterRow()).getAllByRole("button")).toEqual([
      screen.getByRole("button", { name: "All inboxes" }),
      screen.getByRole("button", { name: "Inbox settings" }),
      screen.getByRole("button", { name: "Sort: Newest first" }),
      screen.getByRole("button", { name: "Refresh inbox" }),
    ]);
    expect(filterRow().compareDocumentPosition(screen.getByRole("group", { name: "Fan List filters" })))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("with no split, the \"All inboxes\" selector's menu offers \"All inboxes\" as its only group entry, and choosing it closes the menu", async () => {
    const user = userEvent.setup();
    renderFilters();
    const selector = screen.getByRole("button", { name: "All inboxes" });
    expect(selector).toHaveAttribute("aria-expanded", "false");

    await user.click(selector);
    expect(selector).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("region", { name: "Inboxes" });
    const groups = within(menu).getByRole("group", { name: "Inbox groups" });
    expect(within(groups).getAllByRole("button").map((b) => b.textContent)).toEqual(["All inboxes"]);

    await user.click(within(menu).getByRole("button", { name: "All inboxes" }));
    expect(screen.queryByRole("region", { name: "Inboxes" })).not.toBeInTheDocument();
  });

  it("offers an owner \"Split Inbox settings\" after \"All inboxes\", which closes the menu and opens the settings", async () => {
    const user = userEvent.setup();
    const { onOpenSplitInbox } = renderFilters();
    await user.click(screen.getByRole("button", { name: "All inboxes" }));
    const menu = screen.getByRole("region", { name: "Inboxes" });

    expect(within(menu).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["All inboxes", "Split Inbox settings"]);
    await user.click(within(menu).getByRole("button", { name: "Split Inbox settings" }));
    expect(onOpenSplitInbox).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("region", { name: "Inboxes" })).not.toBeInTheDocument();
  });

  it("does not offer \"Split Inbox settings\" to a chatter-only session", async () => {
    const user = userEvent.setup();
    renderFilters({ onOpenSplitInbox: null });
    await user.click(screen.getByRole("button", { name: "All inboxes" }));
    const menu = screen.getByRole("region", { name: "Inboxes" });

    expect(within(menu).queryByRole("button", { name: "Split Inbox settings" })).not.toBeInTheDocument();
    expect(within(menu).getAllByRole("button").map((b) => b.textContent)).toEqual(["All inboxes"]);
  });

  it("with a count of 3, the selector's menu lists \"All inboxes\", \"Inbox 1\" to \"Inbox 3\", then \"Split Inbox settings\"; choosing a group reports it, and the label shows the chosen entry", async () => {
    const user = userEvent.setup();
    const { onGroupChange } = renderFilters({ groupCount: 3 });
    await user.click(screen.getByRole("button", { name: "All inboxes" }));
    const menu = screen.getByRole("region", { name: "Inboxes" });

    expect(within(menu).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["All inboxes", "Inbox 1", "Inbox 2", "Inbox 3", "Split Inbox settings"]);
    await user.click(within(menu).getByRole("button", { name: "Inbox 2" }));
    expect(onGroupChange).toHaveBeenCalledWith(2);
    expect(screen.queryByRole("region", { name: "Inboxes" })).not.toBeInTheDocument();
    cleanup();

    // With "Inbox 2" chosen the selector reads it, and "All inboxes" reports no group.
    const chosen = renderFilters({ groupCount: 3, group: 2 });
    await user.click(within(filterRow()).getByRole("button", { name: "Inbox 2" }));
    await user.click(within(screen.getByRole("region", { name: "Inboxes" })).getByRole("button", { name: "All inboxes" }));
    expect(chosen.onGroupChange).toHaveBeenCalledWith(null);
  });

  it("hides the \"All inboxes\" selector when it is not to be shown (All Models)", () => {
    renderFilters({ showInboxSelector: false });

    expect(screen.queryByRole("button", { name: /All inboxes/ })).not.toBeInTheDocument();
    expect(within(filterRow()).getAllByRole("button")).toEqual([
      screen.getByRole("button", { name: "Inbox settings" }),
      screen.getByRole("button", { name: "Sort: Newest first" }),
      screen.getByRole("button", { name: "Refresh inbox" }),
    ]);
  });

  it("the gear is icon-only and its menu lists Mark all as read, Select chats, Keep fan info panel open, both blur options, Compact media previews, and no Focus mode and no sort choice", async () => {
    const user = userEvent.setup();
    renderFilters();
    const gear = screen.getByRole("button", { name: "Inbox settings" });
    expect(gear).toHaveTextContent(/^$/);

    await user.click(gear);
    const menu = screen.getByRole("region", { name: "Inbox settings" });
    expect(within(menu).getAllByRole("button").map((b) => b.textContent)).toEqual(["✓Mark all as read", "☑Select chats"]);
    expect(within(menu).getAllByRole("checkbox").map((b) => b.closest("label")?.textContent)).toEqual([
      "Keep fan info panel open", "Blur images till hover", "Blur images constant", "Compact media previews",
    ]);
    // The Fan List's old Focus mode (Pause incoming messages, Hide muted) is gone.
    expect(within(menu).queryByText(/Focus|Pause incoming|Hide chats with muted|Only in All/)).not.toBeInTheDocument();
    expect(within(menu).queryAllByRole("radio")).toEqual([]);
    expect(within(menu).queryByText(/Sort by|Newest first|Amount spent|Spend \+/)).not.toBeInTheDocument();
  });

  it("\"Select chats\" closes the gear and enters select mode", async () => {
    const user = userEvent.setup();
    const { onSelectChats } = renderFilters();
    await user.click(screen.getByRole("button", { name: "Inbox settings" }));
    await user.click(screen.getByRole("button", { name: /Select chats/ }));
    expect(onSelectChats).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("region", { name: "Inbox settings" })).not.toBeInTheDocument();
  });

  it("the sort control is an icon button the gear's size, named \"Sort: Newest first\" and at rest by default; its menu lists Sort by, then ✓ Newest first and the three extra orders (no divider between them), the extras each an Inflowwww extra; choosing one reports it and closes the menu", async () => {
    const user = userEvent.setup();
    const cb = renderFilters();
    const sort = within(filterRow()).getByRole("button", { name: "Sort: Newest first" });
    expect(sort).toHaveAttribute("title", "Sort: Newest first");
    expect(sort).toHaveTextContent(/^$/);
    expect(sort).toHaveAttribute("aria-pressed", "false");
    expect(sort).toHaveAttribute("aria-expanded", "false");
    const gear = screen.getByRole("button", { name: "Inbox settings" });
    for (const cls of gear.className.split(" ").filter((c) => /^(w-|h-|min-|md:min-|rounded|border$)/.test(c))) {
      expect(sort).toHaveClass(cls);
    }

    await user.click(sort);
    expect(sort).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("region", { name: "Sort" });
    // The header first, then the four orders, nothing between them.
    expect(Array.from(menu.children, (el) => el.textContent)).toEqual([
      "Sort by",
      "✓Newest first",
      "Amount spent",
      "Spend + unread on top unread → owe reply → idle",
      "Spend + recency spend × time-decay",
    ]);
    expect(within(menu).queryByRole("separator")).not.toBeInTheDocument();
    const entries = within(menu).getAllByRole("button");
    expect(entries.map((b) => b.textContent)).toEqual([
      "✓Newest first",
      "Amount spent",
      "Spend + unread on top unread → owe reply → idle",
      "Spend + recency spend × time-decay",
    ]);
    expect(entries.map((b) => b.getAttribute("aria-pressed"))).toEqual(["true", "false", "false", "false"]);
    expect(entries.map((b) => b.getAttribute("title"))).toEqual([
      null,
      "Inflowwww extra — Extra sort orders",
      "Inflowwww extra — Extra sort orders\nUnread → owe-reply → idle, spend desc within each tier",
      "Inflowwww extra — Extra sort orders\nSpend × decay. Half-life: idle 1h, owe-reply 2h, unread 3h. Below $3 effective, unread wins.",
    ]);

    await user.click(within(menu).getByRole("button", { name: /^Spend \+ recency/ }));
    expect(cb.onSortModeChange).toHaveBeenCalledTimes(1);
    expect(cb.onSortModeChange).toHaveBeenLastCalledWith("hybrid");
    expect(cb.onActiveChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Sort" })).not.toBeInTheDocument();

    await user.click(sort);
    await user.click(within(screen.getByRole("region", { name: "Sort" })).getByRole("button", { name: "Newest first" }));
    expect(cb.onSortModeChange).toHaveBeenLastCalledWith("recent");
  });

  it("while an extra order is in force the sort control is active and named by it, and its menu's ✓ moves to that order", async () => {
    const user = userEvent.setup();
    // Stateless: the parent stores the reported order and passes it back.
    for (const [mode, label] of [["spend", "Amount spent"], ["spend-unread", "Spend + unread on top"], ["hybrid", "Spend + recency"]] as const) {
      renderFilters({ sortMode: mode });
      const sort = within(filterRow()).getByRole("button", { name: `Sort: ${label}` });
      expect(sort).toHaveAttribute("title", `Sort: ${label}`);
      expect(sort).toHaveAttribute("aria-pressed", "true");
      expect(sort).toHaveClass("bg-accent", "text-white");

      await user.click(sort);
      const entries = within(screen.getByRole("region", { name: "Sort" })).getAllByRole("button");
      const marked = entries.filter((b) => b.textContent?.startsWith("✓"));
      expect(marked.map((b) => b.getAttribute("aria-pressed"))).toEqual(["true"]);
      expect(marked[0]).toHaveTextContent(new RegExp(`^✓${label.replace(/[+]/g, "\\+")}`));
      cleanup();
    }
  });

  it("closes the sort menu on Escape and on a pointer-down outside it, not on one inside it", async () => {
    const user = userEvent.setup();
    renderFilters();
    const menu = () => screen.queryByRole("region", { name: "Sort" });

    await user.click(screen.getByRole("button", { name: "Sort: Newest first" }));
    fireEvent.pointerDown(menu()!);
    expect(menu()).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(menu()).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sort: Newest first" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "All" }));
    expect(menu()).not.toBeInTheDocument();
  });

  it("the refresh icon reports a refresh, and is disabled while the list is fetching", async () => {
    const cb = renderFilters();

    await userEvent.click(screen.getByRole("button", { name: "Refresh inbox" }));
    expect(cb.onRefresh).toHaveBeenCalledTimes(1);

    cleanup();
    renderFilters({ fetching: true });
    expect(screen.getByRole("button", { name: "Refresh inbox" })).toBeDisabled();
  });

  it("reports the filter of the chip that was clicked", async () => {
    const cb = renderFilters();

    await userEvent.click(screen.getByRole("button", { name: "Pinned" }));
    expect(cb.onActiveChange).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "builtin", key: "pinned" });
  });

  it("renders the chips All, Owe reply tagged as an extra, then Infloww's Pinned, Unread, With Tips, then the folders in the same scroller, then Priority tagged as an extra, with no \"+\" Extras overflow and no emoji", () => {
    renderFilters({ pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }], hasLists: true });

    const chipRow = screen.getByRole("group", { name: "Fan List filters" });
    const chips = within(chipRow).getAllByRole("button").map((b) => b.textContent);
    expect(chips).toEqual(["All", "Owe reply", "Pinned", "Unread", "With Tips", "Folder Fixture Folder", "Priority"]);
    expect(screen.queryByRole("button", { name: "Inflowwww extras" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /✎ Lists/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Priority" })).toHaveAttribute("title", "Inflowwww extra — Priority chip");
    expect(screen.getByRole("button", { name: "With Tips" })).not.toHaveAttribute("title");
    expect(screen.queryByRole("group", { name: "Chat folders" })).not.toBeInTheDocument();
  });

  it("With Tips reports OF's who_tipped filter and shows its count only while active", async () => {
    const cb = renderFilters({ activeCount: 2 });
    expect(screen.getByRole("button", { name: "With Tips" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "With Tips" }));
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "builtin", key: "who_tipped" });

    cleanup();
    renderFilters({ active: { kind: "builtin", key: "who_tipped" }, activeCount: 2 });
    expect(screen.getByRole("button", { name: "With Tips 2" })).toHaveAttribute("aria-pressed", "true");
  });

  it("Unread with tips shows after With Tips only while the Creator has tips on, and reports OF's unread_tips filter", async () => {
    renderFilters();
    expect(screen.queryByRole("button", { name: "Unread with tips" })).not.toBeInTheDocument();

    cleanup();
    const cb = renderFilters({ tipsEnabled: true });
    const chips = within(screen.getByRole("group", { name: "Fan List filters" })).getAllByRole("button").map((b) => b.textContent);
    expect(chips.slice(4, 6)).toEqual(["With Tips", "Unread with tips"]);
    await userEvent.click(screen.getByRole("button", { name: "Unread with tips" }));
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "builtin", key: "unread_tips" });

    cleanup();
    renderFilters({ tipsEnabled: true, active: { kind: "builtin", key: "unread_tips" }, activeCount: 3 });
    expect(screen.getByRole("button", { name: "Unread with tips 3" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the Unread count in a corner badge, no badge on All, and Pinned and Priority counts only while active", () => {
    renderFilters({ unreadCount: 4, activeCount: 7 });
    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unread 4" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pinned" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Priority" })).toBeInTheDocument();

    cleanup();
    renderFilters({ active: { kind: "builtin", key: "pinned" }, unreadCount: 4, activeCount: 7 });
    expect(screen.getByRole("button", { name: "Unread 4" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pinned 7" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Priority" })).toBeInTheDocument();

    cleanup();
    renderFilters({ active: { kind: "builtin", key: "priority" }, unreadCount: 0, activeCount: 7 });
    expect(screen.getByRole("button", { name: "Unread" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pinned" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Priority 7" })).toBeInTheDocument();
  });

  it("the Owe reply chip follows All with its count always in the amber badge and the Inflowwww extra tooltip, and reports Owe reply", async () => {
    const cb = renderFilters({ oweReplyCount: 3 });
    const chipRow = screen.getByRole("group", { name: "Fan List filters" });
    const oweReply = within(chipRow).getByRole("button", { name: "Owe reply 3" });
    expect(within(chipRow).getAllByRole("button").indexOf(oweReply)).toBe(1);
    expect(oweReply).toHaveAttribute("title",
      "Inflowwww extra — Owe reply\nChats where the fan sent the last message and we haven't replied");
    expect(oweReply).toHaveAttribute("aria-pressed", "false");
    expect(within(oweReply).getByText("3")).toHaveClass("bg-warn");

    await userEvent.click(oweReply);
    expect(cb.onActiveChange).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "builtin", key: "owe-reply" });
  });

  it("marks the Owe reply chip active while Owe reply is the active filter, its amber count unchanged", () => {
    renderFilters({ active: { kind: "builtin", key: "owe-reply" }, oweReplyCount: 3, activeCount: 9 });
    const oweReply = screen.getByRole("button", { name: "Owe reply 3" });
    expect(oweReply).toHaveAttribute("aria-pressed", "true");
    expect(within(oweReply).getByText("3")).toHaveClass("bg-warn");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");

    cleanup();
    renderFilters({ oweReplyCount: 0 });
    expect(screen.getByRole("button", { name: "Owe reply" })).toHaveAttribute("aria-pressed", "false");
  });

  it("reports the folder of the folder chip that was clicked", async () => {
    const cb = renderFilters({ pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }], hasLists: true });

    await userEvent.click(screen.getByRole("button", { name: "Folder Fixture Folder" }));
    expect(cb.onActiveChange).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "folder", listId: "700000001" });
  });

  it("renders the pinned folders as plain chips showing only the name (Infloww's list chip), and the filter row's pencil opens the folder picker", async () => {
    const cb = renderFilters({
      pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }, { id: 700000002, name: "Second Fixture Folder" }],
      hasLists: true,
    });
    const chipRow = screen.getByRole("group", { name: "Fan List filters" });

    expect(within(chipRow).getAllByRole("button").slice(5, 8)).toEqual([
      screen.getByRole("button", { name: "Folder Fixture Folder" }),
      screen.getByRole("button", { name: "Folder Second Fixture Folder" }),
      screen.getByRole("button", { name: "Priority" }),
    ]);
    for (const name of ["Fixture Folder", "Second Fixture Folder"]) {
      const chip = within(chipRow).getByRole("button", { name: `Folder ${name}` });
      expect(within(chip).queryByRole("img")).not.toBeInTheDocument();
      expect(within(chip).getByText("Folder")).toHaveClass("sr-only");
    }
    expect(chipRow).not.toHaveTextContent("📂");

    await userEvent.click(within(filterRow()).getByRole("button", { name: "Pin lists as chips" }));
    expect(cb.onOpenFolderPicker).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).not.toHaveBeenCalled();
  });

  it("offers the pencil, an icon button the gear's size after the sort control, only when the Creator has a list", () => {
    const chipTexts = () => within(screen.getByRole("group", { name: "Fan List filters" })).getAllByRole("button").map((b) => b.textContent);
    renderFilters({ hasLists: true });
    const pencil = within(filterRow()).getByRole("button", { name: "Pin lists as chips" });
    expect(pencil).toHaveAttribute("title", "Pin lists as chips");
    expect(pencil).toHaveTextContent(/^$/);
    expect(pencil).toHaveClass("border", "border-border");
    expect(within(filterRow()).getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual([
      "All inboxes", "Inbox settings", "Sort: Newest first", "Pin lists as chips", "Refresh inbox",
    ]);
    expect(chipTexts()).toEqual(["All", "Owe reply", "Pinned", "Unread", "With Tips", "Priority"]);

    cleanup();
    renderFilters({ hasLists: false });
    expect(screen.queryByRole("button", { name: /Pin lists|Lists|✎/ })).not.toBeInTheDocument();

    cleanup();
    renderFilters({ hasLists: false, pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }] });
    expect(chipTexts()).toEqual(["All", "Owe reply", "Pinned", "Unread", "With Tips", "Folder Fixture Folder", "Priority"]);
  });

  it("re-clicking the active folder chip clears it back to All", async () => {
    const folders = [{ id: 700000001, name: "Fixture Folder" }, { id: 700000002, name: "Second Fixture Folder" }];
    const cb = renderFilters({ pinnedFolders: folders, hasLists: true, active: { kind: "folder", listId: "700000001" } });
    expect(screen.getByRole("button", { name: "Folder Fixture Folder" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Folder Second Fixture Folder" })).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(screen.getByRole("button", { name: "Folder Fixture Folder" }));
    expect(cb.onActiveChange).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "builtin", key: "all" });

    // Clicking the other folder switches to it rather than clearing.
    await userEvent.click(screen.getByRole("button", { name: "Folder Second Fixture Folder" }));
    expect(cb.onActiveChange).toHaveBeenCalledTimes(2);
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "folder", listId: "700000002" });
  });
});
