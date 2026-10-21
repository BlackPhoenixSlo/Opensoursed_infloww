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
import { FOCUS_MODE_DEFAULTS } from "./useFocusModeSettings";

function renderFilters(props: Partial<Parameters<typeof FanListFilters>[0]> = {}) {
  const callbacks = {
    onActiveChange: vi.fn(), onOpenFolderPicker: vi.fn(), onRefresh: vi.fn(), onMarkAllRead: vi.fn(),
    onKeepDrawerOpenChange: vi.fn(), onBlurModeChange: vi.fn(), onCompactMediaChange: vi.fn(), onSortModeChange: vi.fn(),
    onFocusModeChange: vi.fn(), onOpenSplitInbox: vi.fn(), onGroupChange: vi.fn(),
    onFocusSettingsChange: vi.fn(), onSelectChats: vi.fn(),
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
      focusMode={false}
      focusSettings={FOCUS_MODE_DEFAULTS}
      searching={false}
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
      screen.getByRole("button", { name: "Newest first" }),
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
      screen.getByRole("button", { name: "Newest first" }),
      screen.getByRole("button", { name: "Refresh inbox" }),
    ]);
  });

  it("the gear is icon-only and its menu lists Mark all as read, Select chats, Keep fan info panel open, both blur options, Compact media previews and Focus mode, and no sort choice", async () => {
    const user = userEvent.setup();
    renderFilters();
    const gear = screen.getByRole("button", { name: "Inbox settings" });
    expect(gear).toHaveTextContent(/^$/);

    await user.click(gear);
    const menu = screen.getByRole("region", { name: "Inbox settings" });
    expect(within(menu).getAllByRole("button").map((b) => b.textContent)).toEqual(["✓Mark all as read", "☑Select chats"]);
    expect(within(menu).getAllByRole("checkbox").map((b) => b.closest("label")?.textContent)).toEqual([
      "Keep fan info panel open", "Blur images till hover", "Blur images constant", "Compact media previews", "Focus mode",
    ]);
    expect(within(menu).queryAllByRole("radio")).toEqual([]);
    expect(within(menu).queryByText(/Sort by|Newest first|Amount spent|Spend \+/)).not.toBeInTheDocument();
  });

  it("the Focus mode checkbox is enabled only on All with Newest first, and reports its choice there", async () => {
    const user = userEvent.setup();
    const { onFocusModeChange } = renderFilters();
    await user.click(screen.getByRole("button", { name: "Inbox settings" }));
    const focus = screen.getByRole("checkbox", { name: "Focus mode" });
    expect(focus).toBeEnabled();
    expect(focus).not.toHaveAccessibleDescription();
    await user.click(focus);
    expect(onFocusModeChange).toHaveBeenCalledWith(true);
  });

  it("\"Select chats\" closes the gear and enters select mode", async () => {
    const user = userEvent.setup();
    const { onSelectChats } = renderFilters();
    await user.click(screen.getByRole("button", { name: "Inbox settings" }));
    await user.click(screen.getByRole("button", { name: /Select chats/ }));
    expect(onSelectChats).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("region", { name: "Inbox settings" })).not.toBeInTheDocument();
  });

  it("with Focus mode on, its two settings show under it and report each change; off or unavailable, they are not offered", async () => {
    const user = userEvent.setup();
    const { onFocusSettingsChange } = renderFilters({ focusMode: true });
    await user.click(screen.getByRole("button", { name: "Inbox settings" }));
    const group = screen.getByRole("group", { name: "Focus mode settings" });
    expect(within(group).getAllByRole("checkbox").map((b) => [b.closest("label")?.textContent, (b as HTMLInputElement).checked]))
      .toEqual([
        ["Pause incoming messages", true],
        ["Hide chats with muted notifications", false],
      ]);
    await user.click(within(group).getByRole("checkbox", { name: "Hide chats with muted notifications" }));
    expect(onFocusSettingsChange).toHaveBeenCalledWith({ pause: true, hideMuted: true });
    cleanup();

    for (const props of [{ focusMode: false }, { focusMode: true, searching: true }]) {
      renderFilters(props);
      await user.click(screen.getByRole("button", { name: "Inbox settings" }));
      expect(screen.queryByRole("group", { name: "Focus mode settings" })).not.toBeInTheDocument();
      cleanup();
    }
  });

  it("the Focus mode checkbox is disabled outside All with Newest first, and reads \"Only in All · Newest first\"", async () => {
    const user = userEvent.setup();
    const outside = [
      { active: { kind: "builtin", key: "unread" } },
      { active: { kind: "builtin", key: "owe-reply" } },
      { active: { kind: "folder", listId: "700000001" } },
      { sortMode: "spend" },
      { searching: true },
    ] as const;
    for (const props of outside) {
      const { onFocusModeChange } = renderFilters({ ...props, focusMode: true });
      await user.click(screen.getByRole("button", { name: "Inbox settings" }));
      const focus = screen.getByRole("checkbox", { name: "Focus mode" });
      expect(focus).toBeDisabled();
      expect(focus).toBeChecked();
      expect(focus).toHaveAccessibleDescription("Only in All · Newest first");
      expect(screen.getByText("Only in All · Newest first")).toBeVisible();
      await user.click(focus);
      expect(onFocusModeChange).not.toHaveBeenCalled();
      cleanup();
    }
  });

  it("the sort control reads \"Newest first\" by default, and its menu lists no extra order", async () => {
    const user = userEvent.setup();
    const cb = renderFilters();
    const sort = within(filterRow()).getByRole("button", { name: "Newest first" });
    expect(sort).toHaveAttribute("aria-expanded", "false");

    await user.click(sort);
    expect(sort).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("region", { name: "Sort" });
    expect(within(menu).getAllByRole("button").map((b) => b.textContent)).toEqual(["Newest first"]);

    await user.click(within(menu).getByRole("button", { name: "Newest first" }));
    expect(cb.onSortModeChange).toHaveBeenCalledTimes(1);
    expect(cb.onSortModeChange).toHaveBeenLastCalledWith("recent");
    expect(screen.queryByRole("region", { name: "Sort" })).not.toBeInTheDocument();
  });

  it("the \"+\" overflow lists the three extra orders after ↩ Owe reply, each an Inflowwww extra; choosing one reports it and the sort control shows its name", async () => {
    const user = userEvent.setup();
    const cb = renderFilters({ oweReplyCount: 3 });

    await user.click(screen.getByRole("button", { name: "Inflowwww extras" }));
    const overflow = screen.getByRole("region", { name: "Inflowwww extras" });
    const entries = within(overflow).getAllByRole("button");
    expect(entries.map((b) => b.textContent)).toEqual([
      "↩ Owe reply 3",
      "Amount spent",
      "Spend + unread on top unread → owe reply → idle",
      "Spend + recency spend × time-decay",
    ]);
    expect(entries.map((b) => b.getAttribute("title"))).toEqual([
      "Inflowwww extra — Owe reply\nChats where the fan sent the last message and we haven't replied",
      "Inflowwww extra — Extra sort orders",
      "Inflowwww extra — Extra sort orders\nUnread → owe-reply → idle, spend desc within each tier",
      "Inflowwww extra — Extra sort orders\nSpend × decay. Half-life: idle 1h, owe-reply 2h, unread 3h. Below $3 effective, unread wins.",
    ]);

    await user.click(within(overflow).getByRole("button", { name: /^Spend \+ recency/ }));
    expect(cb.onSortModeChange).toHaveBeenCalledTimes(1);
    expect(cb.onSortModeChange).toHaveBeenLastCalledWith("hybrid");
    expect(cb.onActiveChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Inflowwww extras" })).not.toBeInTheDocument();

    // Stateless: the parent stores the reported order and passes it back.
    cleanup();
    renderFilters({ sortMode: "hybrid" });
    expect(within(filterRow()).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "All inboxes", "", "Spend + recency", "",
    ]);
    cleanup();
    renderFilters({ sortMode: "spend" });
    expect(within(filterRow()).getByRole("button", { name: "Amount spent" })).toBeInTheDocument();
    cleanup();
    renderFilters({ sortMode: "spend-unread" });
    expect(within(filterRow()).getByRole("button", { name: "Spend + unread on top" })).toBeInTheDocument();
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

  it("renders the chips in Infloww's order, All, Pinned, Unread, With Tips, then the folders and \"✎ Lists\" in the same scroller, then Priority tagged as an extra, then the \"+\" Extras overflow, with no emoji", () => {
    renderFilters({ pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }], hasLists: true });

    const chipRow = screen.getByRole("group", { name: "Fan List filters" });
    const chips = within(chipRow).getAllByRole("button").map((b) => b.textContent);
    expect(chips).toEqual(["All", "Pinned", "Unread", "With Tips", "Folder Fixture Folder", "✎ Lists", "Priority", "+"]);
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
    expect(chips.slice(3, 5)).toEqual(["With Tips", "Unread with tips"]);
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

  it("the \"+\" overflow holds ↩ Owe reply with its count and the Inflowwww extra tooltip, and choosing it reports Owe reply", async () => {
    const cb = renderFilters({ oweReplyCount: 3 });
    const plus = screen.getByRole("button", { name: "Inflowwww extras" });
    expect(plus).toHaveAttribute("title", "Inflowwww extras");
    expect(plus).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /Owe reply/ })).not.toBeInTheDocument();

    await userEvent.click(plus);
    expect(plus).toHaveAttribute("aria-expanded", "true");
    const overflow = screen.getByRole("region", { name: "Inflowwww extras" });
    const oweReply = within(overflow).getByRole("button", { name: "↩ Owe reply 3" });
    expect(oweReply).toHaveAttribute("title",
      "Inflowwww extra — Owe reply\nChats where the fan sent the last message and we haven't replied");
    expect(within(oweReply).getByText("3")).toHaveClass("text-warn");

    await userEvent.click(oweReply);
    expect(cb.onActiveChange).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "builtin", key: "owe-reply" });
    expect(screen.queryByRole("region", { name: "Inflowwww extras" })).not.toBeInTheDocument();
  });

  it("closes the \"+\" overflow on Escape and on a pointer-down outside it, not on one inside it", async () => {
    const user = userEvent.setup();
    renderFilters();
    const overflow = () => screen.queryByRole("region", { name: "Inflowwww extras" });

    await user.click(screen.getByRole("button", { name: "Inflowwww extras" }));
    fireEvent.pointerDown(overflow()!);
    expect(overflow()).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(overflow()).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Inflowwww extras" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "All" }));
    expect(overflow()).not.toBeInTheDocument();
  });

  it("marks the \"+\" chip active with the owe-reply count only while Owe reply is the active filter", () => {
    renderFilters({ active: { kind: "builtin", key: "owe-reply" }, oweReplyCount: 3 });
    const plus = screen.getByRole("button", { name: "Inflowwww extras" });
    expect(plus).toHaveAttribute("aria-pressed", "true");
    expect(within(plus).getByText("3")).toHaveClass("bg-warn");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");

    cleanup();
    renderFilters({ active: { kind: "builtin", key: "all" }, oweReplyCount: 3 });
    expect(screen.getByRole("button", { name: "Inflowwww extras" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });

  it("reports the folder of the folder chip that was clicked", async () => {
    const cb = renderFilters({ pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }], hasLists: true });

    await userEvent.click(screen.getByRole("button", { name: "Folder Fixture Folder" }));
    expect(cb.onActiveChange).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).toHaveBeenLastCalledWith({ kind: "folder", listId: "700000001" });
  });

  it("renders the pinned folders as plain chips showing only the name (Infloww's list chip), followed by \"✎ Lists\", which opens the folder picker", async () => {
    const cb = renderFilters({
      pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }, { id: 700000002, name: "Second Fixture Folder" }],
      hasLists: true,
    });
    const chipRow = screen.getByRole("group", { name: "Fan List filters" });

    expect(within(chipRow).getAllByRole("button").slice(4, 7)).toEqual([
      screen.getByRole("button", { name: "Folder Fixture Folder" }),
      screen.getByRole("button", { name: "Folder Second Fixture Folder" }),
      screen.getByRole("button", { name: "✎ Lists" }),
    ]);
    for (const name of ["Fixture Folder", "Second Fixture Folder"]) {
      const chip = within(chipRow).getByRole("button", { name: `Folder ${name}` });
      expect(within(chip).queryByRole("img")).not.toBeInTheDocument();
      expect(within(chip).getByText("Folder")).toHaveClass("sr-only");
    }
    expect(chipRow).not.toHaveTextContent("📂");

    await userEvent.click(within(chipRow).getByRole("button", { name: "✎ Lists" }));
    expect(cb.onOpenFolderPicker).toHaveBeenCalledTimes(1);
    expect(cb.onActiveChange).not.toHaveBeenCalled();
  });

  it("offers \"✎ Lists\" only when the Creator has a list", () => {
    const chipTexts = () => within(screen.getByRole("group", { name: "Fan List filters" })).getAllByRole("button").map((b) => b.textContent);
    renderFilters({ hasLists: true });
    expect(chipTexts()).toEqual(["All", "Pinned", "Unread", "With Tips", "✎ Lists", "Priority", "+"]);

    cleanup();
    renderFilters({ hasLists: false });
    expect(screen.queryByRole("button", { name: /Lists|✎/ })).not.toBeInTheDocument();

    cleanup();
    renderFilters({ hasLists: false, pinnedFolders: [{ id: 700000001, name: "Fixture Folder" }] });
    expect(chipTexts()).toEqual(["All", "Pinned", "Unread", "With Tips", "Folder Fixture Folder", "Priority", "+"]);
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
