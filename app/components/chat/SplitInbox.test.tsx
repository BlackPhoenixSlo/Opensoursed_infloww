import { useState } from "react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { RelayError } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { SplitInbox } from "./SplitInbox";

const relayMock = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: relayMock,
}));

const rosterMock = vi.hoisted(() => ({ rows: [] as unknown[] }));
vi.mock("@/hooks/useRoster", () => ({ useRoster: () => ({ rows: rosterMock.rows }) }));
vi.mock("@/hooks/useAccounts", async (orig) => ({
  ...(await orig<typeof import("@/hooks/useAccounts")>()),
  usePlatformAccounts: () => [
    { id: "100000001", nickname: "Fixture Creator One" },
    { id: "100000009", nickname: "Fixture Creator Nine" },
  ],
}));

const ACCOUNT_ID = "100000001";
const ROSTER = [
  { chatter_id: "c-a", display_name: "Fixture Chatter A", is_active: true, kind: "login", account_ids: null },
  { chatter_id: "c-b", display_name: "Fixture Chatter B", is_active: true, kind: "login", account_ids: [ACCOUNT_ID] },
  { chatter_id: "c-x", display_name: "Fixture Chatter X", is_active: true, kind: "login", account_ids: ["100000009"] },
];
const STORED = { group_count: 3, assignments: { "200000001": 2 } };
const FANS = [
  { id: 200000001, name: "Fixture Fan One", accountId: ACCOUNT_ID },
  { id: 200000002, name: "Fixture Fan Two", accountId: ACCOUNT_ID },
  { id: 200000003, name: "Fixture Fan Three", accountId: ACCOUNT_ID },
];
let stored: { group_count: number; assignments: Record<string, number>; chatter_groups?: Record<string, number> } = STORED;

function Host() {
  const [open, setOpen] = useState(true);
  return <SplitInbox scope="model" accountIds={[ACCOUNT_ID]} open={open} onClose={() => setOpen(false)} fans={FANS} />;
}

const dialog = () => screen.queryByRole("dialog", { name: "Split Inbox settings" });
const countSelect = async () =>
  within((await screen.findByRole("dialog", { name: "Split Inbox settings" })))
    .findByRole("combobox", { name: "Choose the number of groups" });

const fanSelect = (name: string) =>
  within(screen.getByRole("region", { name: "Reassign fans to different groups" })).getByRole("combobox", { name });
const optionsOf = (select: HTMLElement) => within(select).getAllByRole("option").map((o) => o.textContent);

beforeEach(() => {
  stored = STORED;
  rosterMock.rows = [];
  relayMock.get.mockImplementation((path: string) =>
    path.startsWith(`/admin/split-inbox?account_id=${ACCOUNT_ID}`)
      ? Promise.resolve({ account_id: ACCOUNT_ID, config: stored })
      : Promise.reject(new Error(`unrouted GET ${path}`)));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SplitInbox", () => {
  it("All Models with one Creator saves the default and hides per-fan moves", async () => {
    const user = userEvent.setup();
    relayMock.patch.mockResolvedValue({ configs: {} });
    renderWithProviders(<SplitInbox scope="all" accountIds={[ACCOUNT_ID]} open onClose={() => {}} fans={FANS} />);
    await user.selectOptions(await countSelect(), "2");
    expect(screen.getByText("Applies to this model and new ones")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Reassign fans to different groups" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(relayMock.patch).toHaveBeenCalledWith("/admin/split-inbox", {
      account_ids: [ACCOUNT_ID], group_count: 2, as_default: true,
    });
  });

  it("the count select offers exactly 1 to 9 and starts at the stored count", async () => {
    renderWithProviders(<Host />);
    const select = await countSelect();

    expect(within(select).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9"]);
    expect(select).toHaveValue("3");
  });

  it("Save PATCHes only the edited count once and closes the dialog", async () => {
    const user = userEvent.setup();
    relayMock.patch.mockResolvedValue({ configs: {} });
    renderWithProviders(<Host />);
    await user.selectOptions(await countSelect(), "5");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(relayMock.patch).toHaveBeenCalledTimes(1);
    expect(relayMock.patch).toHaveBeenCalledWith("/admin/split-inbox", { account_ids: [ACCOUNT_ID], group_count: 5 });
    await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
  });

  it("opens on a fresh read, not the cached split another device has since changed", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["split-inbox", ACCOUNT_ID], { account_id: ACCOUNT_ID, config: { group_count: 2, assignments: {} } });
    renderWithProviders(<Host />, client);
    expect(screen.queryByRole("combobox", { name: "Choose the number of groups" })).not.toBeInTheDocument();
    expect(await countSelect()).toHaveValue("3");
  });

  it("a failed PATCH keeps the dialog open with the relay's error, and Save again resends the same edits", async () => {
    const user = userEvent.setup();
    relayMock.patch
      .mockRejectedValueOnce(new RelayError(403, null, "owner-only endpoint — chatter sessions cannot perform this action"))
      .mockResolvedValueOnce({ configs: {} });
    renderWithProviders(<Host />);
    await user.selectOptions(await countSelect(), "2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert"))
      .toHaveTextContent("owner-only endpoint — chatter sessions cannot perform this action");
    expect(dialog()).toBeInTheDocument();
    await vi.waitFor(() => expect(relayMock.get).toHaveBeenCalledTimes(2));
    expect(await countSelect()).toHaveValue("2");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(relayMock.patch.mock.calls).toEqual([
      ["/admin/split-inbox", { account_ids: [ACCOUNT_ID], group_count: 2 }],
      ["/admin/split-inbox", { account_ids: [ACCOUNT_ID], group_count: 2 }],
    ]);
    await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
  });

  it("a 409 shows the relay's error and reloads the form on the current split, so Save again uses it", async () => {
    const user = userEvent.setup();
    rosterMock.rows = ROSTER;
    const conflict = "Split Inbox changed elsewhere: Inbox 3 no longer exists. Review the settings and save again.";
    relayMock.patch.mockRejectedValueOnce(new RelayError(409, null, conflict)).mockResolvedValueOnce({ configs: {} });
    renderWithProviders(<Host />);
    await countSelect();
    const chatterB = () => within(screen.getByRole("region", { name: "Chatters" }))
      .getByRole("combobox", { name: "Fixture Chatter B" });
    await user.selectOptions(chatterB(), "Inbox 3");
    await user.selectOptions(fanSelect("Fixture Fan Two"), "Inbox 3");
    stored = { group_count: 2, assignments: {} };
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(conflict);
    await vi.waitFor(() => expect(screen.getByRole("combobox", { name: "Choose the number of groups" })).toHaveValue("2"));
    expect(optionsOf(chatterB())).toEqual(["All", "Inbox 1", "Inbox 2"]);
    expect(chatterB()).toHaveValue("");
    await user.selectOptions(chatterB(), "Inbox 2");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(relayMock.patch.mock.calls).toEqual([
      ["/admin/split-inbox", { account_ids: [ACCOUNT_ID], chatter_groups: { "c-b": 3 }, assignments: { "200000002": 3 } }],
      ["/admin/split-inbox", { account_ids: [ACCOUNT_ID], chatter_groups: { "c-b": 2 } }],
    ]);
    await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
  });

  it("switching to another model while open lists only the opened model's Fans", async () => {
    const OTHER_ID = "100000009";
    const other = [{ id: 200000009, name: "Fixture Fan Nine", accountId: OTHER_ID }];
    const host = (ids: string[], fans: typeof FANS) => <SplitInbox scope={ids.length === 1 ? "model" : "all"} accountIds={ids} open onClose={() => {}} fans={fans} />;
    const { rerender } = renderWithProviders(host([ACCOUNT_ID], FANS));
    await countSelect();
    rerender(host([OTHER_ID], [...other, ...FANS.slice(0, 1)]));
    const region = screen.getByRole("region", { name: "Reassign fans to different groups" });
    expect(within(region).getAllByRole("combobox").map((s) => s.getAttribute("aria-label"))).toEqual(["Fixture Fan One"]);
  });

  it("reassigning one Fan sends only that Fan's move", async () => {
    const user = userEvent.setup();
    relayMock.patch.mockResolvedValue({ configs: {} });
    renderWithProviders(<Host />);
    const count = await countSelect();
    await user.selectOptions(count, "1");
    expect(screen.queryByRole("region", { name: "Reassign fans to different groups" })).not.toBeInTheDocument();

    await user.selectOptions(count, "4");
    const region = screen.getByRole("region", { name: "Reassign fans to different groups" });
    expect(within(region).getAllByRole("combobox").map((s) => s.getAttribute("aria-label")))
      .toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
    expect(optionsOf(fanSelect("Fixture Fan Two"))).toEqual(["Inbox 1", "Inbox 2", "Inbox 3", "Inbox 4"]);
    expect(fanSelect("Fixture Fan One")).toHaveValue("2");

    const shown = (fanSelect("Fixture Fan Two") as HTMLSelectElement).value;
    const moveTo = shown === "1" ? "2" : "1";
    await user.selectOptions(fanSelect("Fixture Fan Two"), `Inbox ${moveTo}`);
    expect(fanSelect("Fixture Fan Two")).toHaveValue(moveTo);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(relayMock.patch).toHaveBeenCalledTimes(1);
    expect(relayMock.patch).toHaveBeenCalledWith("/admin/split-inbox", {
      account_ids: [ACCOUNT_ID], group_count: 4, assignments: { "200000002": Number(moveTo) },
    });
    await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
  });

  it("lowering N narrows each Fan's choices to the new count and sends just the count", async () => {
    const user = userEvent.setup();
    stored = { group_count: 3, assignments: { "200000001": 2, "200000002": 3 } };
    relayMock.patch.mockResolvedValue({ configs: {} });
    renderWithProviders(<Host />);
    await user.selectOptions(await countSelect(), "2");
    expect(optionsOf(fanSelect("Fixture Fan Two"))).toEqual(["Inbox 1", "Inbox 2"]);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(relayMock.patch).toHaveBeenCalledTimes(1);
    expect(relayMock.patch).toHaveBeenCalledWith("/admin/split-inbox", { account_ids: [ACCOUNT_ID], group_count: 2 });
  });

  it("lists the chatters who see this Creator; binding one sends it, \"All\" sends an unbind", async () => {
    const user = userEvent.setup();
    rosterMock.rows = ROSTER;
    stored = { ...STORED, chatter_groups: { "c-b": 3 } };
    relayMock.patch.mockResolvedValue({ configs: {} });
    renderWithProviders(<Host />);
    await countSelect();
    const region = screen.getByRole("region", { name: "Chatters" });
    expect(within(region).getAllByRole("combobox").map((c) => c.getAttribute("aria-label")))
      .toEqual(["Fixture Chatter A", "Fixture Chatter B"]);
    const a = within(region).getByRole("combobox", { name: "Fixture Chatter A" });
    const b = within(region).getByRole("combobox", { name: "Fixture Chatter B" });
    expect(optionsOf(a)).toEqual(["All", "Inbox 1", "Inbox 2", "Inbox 3"]);
    expect(a).toHaveValue("");
    expect(b).toHaveValue("3");

    await user.selectOptions(a, "Inbox 1");
    await user.selectOptions(b, "All");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(relayMock.patch).toHaveBeenCalledWith("/admin/split-inbox", {
      account_ids: [ACCOUNT_ID], chatter_groups: { "c-a": 1, "c-b": null },
    });
  });

  describe("All Models (more than one Creator)", () => {
    const OTHER_ID = "100000009";
    const IDS = [ACCOUNT_ID, OTHER_ID];
    let splits: Record<string, typeof stored>;
    function AllHost() {
      const [open, setOpen] = useState(true);
      return <SplitInbox scope="all" accountIds={IDS} open={open} onClose={() => setOpen(false)} fans={FANS} />;
    }
    beforeEach(() => {
      splits = {
        [ACCOUNT_ID]: { group_count: 2, assignments: { "200000001": 2 }, chatter_groups: { "c-a": 1 } },
        [OTHER_ID]: { group_count: 3, assignments: { "200000009": 3 }, chatter_groups: { "c-a": 2, "c-x": 1 } },
      };
      relayMock.get.mockImplementation((path: string) => {
        const aid = new URLSearchParams(path.split("?")[1]).get("account_id")!;
        return splits[aid] ? Promise.resolve({ account_id: aid, config: splits[aid] }) : Promise.reject(new Error(path));
      });
    });

    it("applies to every Creator: mixed count, no reassign section, chatters across Creators with Mixed", async () => {
      rosterMock.rows = ROSTER;
      renderWithProviders(<AllHost />);
      const count = await countSelect();
      expect(count).toHaveValue("");
      expect(screen.getByText("Applies to all 2 models and new ones")).toBeInTheDocument();
      expect(screen.getByText("Move single fans from a model's own tab.")).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Reassign fans to different groups" })).not.toBeInTheDocument();
      const region = screen.getByRole("region", { name: "Chatters" });
      expect(within(region).getAllByRole("combobox").map((c) => c.getAttribute("aria-label")))
        .toEqual(["Fixture Chatter A", "Fixture Chatter B", "Fixture Chatter X"]);
      const a = within(region).getByRole("combobox", { name: "Fixture Chatter A" });
      expect(a).toHaveValue("mixed");
      expect(optionsOf(a)).toEqual(["All", "Mixed", "Inbox 1", "Inbox 2"]);
      expect(within(a).getByRole("option", { name: "Mixed" })).toBeDisabled();
      expect(within(region).getByRole("combobox", { name: "Fixture Chatter B" })).toHaveValue("");
      expect(within(region).getByRole("combobox", { name: "Fixture Chatter X" })).toHaveValue("1");
    });

    it("closes on no-op Save without a PATCH", async () => {
      const user = userEvent.setup();
      renderWithProviders(<AllHost />);
      await countSelect();
      await user.click(screen.getByRole("button", { name: "Save" }));
      await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
      expect(relayMock.patch).not.toHaveBeenCalled();
    });

    it("Save sends one PATCH for every Creator carrying only the edits, and closes", async () => {
      const user = userEvent.setup();
      rosterMock.rows = ROSTER;
      relayMock.patch.mockResolvedValue({ configs: {} });
      renderWithProviders(<AllHost />);
      await user.selectOptions(await countSelect(), "2");
      await user.selectOptions(
        within(screen.getByRole("region", { name: "Chatters" })).getByRole("combobox", { name: "Fixture Chatter B" }),
        "Inbox 2",
      );
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(relayMock.patch.mock.calls).toEqual([
        ["/admin/split-inbox", { account_ids: IDS, group_count: 2, chatter_groups: { "c-b": 2 }, as_default: true }],
      ]);
      await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
    });

    it("a Creator joining while the dialog is open is not a save target", async () => {
      const user = userEvent.setup();
      const LATE = "100000005";
      splits[LATE] = { group_count: 4, assignments: { "200000004": 4 } };
      relayMock.patch.mockResolvedValue({ configs: {} });
      const host = (ids: string[]) => <SplitInbox scope={ids.length === 1 ? "model" : "all"} accountIds={ids} open onClose={() => {}} fans={FANS} />;
      const { rerender } = renderWithProviders(host(IDS));
      await countSelect();
      rerender(host([...IDS, LATE]));
      expect(screen.getByText("Applies to all 2 models and new ones")).toBeInTheDocument();
      await user.selectOptions(await countSelect(), "2");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(relayMock.patch.mock.calls).toEqual([["/admin/split-inbox", { account_ids: IDS, group_count: 2, as_default: true }]]);
    });

    it("a failed save keeps the dialog open with the relay's error and the picked count", async () => {
      const user = userEvent.setup();
      relayMock.patch.mockRejectedValue(new RelayError(502, null, "upstream down"));
      renderWithProviders(<AllHost />);
      await user.selectOptions(await countSelect(), "4");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("upstream down");
      expect(relayMock.patch).toHaveBeenCalledTimes(1);
      expect(dialog()).toBeInTheDocument();
      expect(await countSelect()).toHaveValue("4");
    });

    it("a failed read names the Creator and offers no form", async () => {
      delete splits[OTHER_ID];
      renderWithProviders(<AllHost />);
      expect(await screen.findByRole("alert"))
        .toHaveTextContent("Could not load Split Inbox settings for Fixture Creator Nine.");
      expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: "Choose the number of groups" })).not.toBeInTheDocument();
    });
  });
});
