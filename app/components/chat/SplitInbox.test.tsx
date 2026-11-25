import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { RelayError } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { SplitInbox } from "./SplitInbox";

const relayMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
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
  { id: 200000001, name: "Fixture Fan One" },
  { id: 200000002, name: "Fixture Fan Two" },
  { id: 200000003, name: "Fixture Fan Three" },
];
let stored: { group_count: number; assignments: Record<string, number>; chatter_groups?: Record<string, number> } = STORED;

function Host() {
  const [open, setOpen] = useState(true);
  return <SplitInbox accountIds={[ACCOUNT_ID]} open={open} onClose={() => setOpen(false)} fans={FANS} />;
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
  it("the count select offers exactly 1 to 9 and starts at the stored count", async () => {
    renderWithProviders(<Host />);
    const select = await countSelect();

    expect(within(select).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9"]);
    expect(select).toHaveValue("3");
  });

  it("Save PUTs {group_count, assignments} once, carrying the stored moves, and closes the dialog", async () => {
    const user = userEvent.setup();
    relayMock.put.mockResolvedValue({
      account_id: ACCOUNT_ID, config: { group_count: 5, assignments: { "200000001": 2 } },
    });
    renderWithProviders(<Host />);
    await user.selectOptions(await countSelect(), "5");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(relayMock.put).toHaveBeenCalledTimes(1);
    expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 5, assignments: { "200000001": 2 }, chatter_groups: {} },
    });
    await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
  });

  it("a failed PUT keeps the dialog open and shows the relay's error", async () => {
    const user = userEvent.setup();
    relayMock.put.mockRejectedValue(
      new RelayError(403, null, "owner-only endpoint — chatter sessions cannot perform this action"));
    renderWithProviders(<Host />);
    await user.selectOptions(await countSelect(), "2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert"))
      .toHaveTextContent("owner-only endpoint — chatter sessions cannot perform this action");
    expect(dialog()).toBeInTheDocument();
    expect(await countSelect()).toHaveValue("2");
  });

  it("reassigning one Fan changes only that Fan's entry in the PUT body", async () => {
    const user = userEvent.setup();
    relayMock.put.mockImplementation((_path: string, body: { config: unknown }) =>
      Promise.resolve({ account_id: ACCOUNT_ID, ...body }));
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

    expect(relayMock.put).toHaveBeenCalledTimes(1);
    expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 4, assignments: { "200000001": 2, "200000002": Number(moveTo) }, chatter_groups: {} },
    });
    await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
  });

  it("lowering N drops the out-of-range assignments from the PUT body and keeps the in-range ones", async () => {
    const user = userEvent.setup();
    stored = { group_count: 3, assignments: { "200000001": 2, "200000002": 3 } };
    relayMock.put.mockImplementation((_path: string, body: { config: unknown }) =>
      Promise.resolve({ account_id: ACCOUNT_ID, ...body }));
    renderWithProviders(<Host />);
    await user.selectOptions(await countSelect(), "2");
    expect(optionsOf(fanSelect("Fixture Fan Two"))).toEqual(["Inbox 1", "Inbox 2"]);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(relayMock.put).toHaveBeenCalledTimes(1);
    expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 2, assignments: { "200000001": 2 }, chatter_groups: {} },
    });
  });

  it("lists the chatters who see this Creator; binding one PUTs chatter_groups, \"All\" unbinds", async () => {
    const user = userEvent.setup();
    rosterMock.rows = ROSTER;
    stored = { ...STORED, chatter_groups: { "c-b": 3 } };
    relayMock.put.mockImplementation((_path: string, body: { config: unknown }) =>
      Promise.resolve({ account_id: ACCOUNT_ID, ...body }));
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

    expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 3, assignments: { "200000001": 2 }, chatter_groups: { "c-a": 1 } },
    });
  });

  describe("All Models (more than one Creator)", () => {
    const OTHER_ID = "100000009";
    const IDS = [ACCOUNT_ID, OTHER_ID];
    let splits: Record<string, typeof stored>;
    function AllHost() {
      const [open, setOpen] = useState(true);
      return <SplitInbox accountIds={IDS} open={open} onClose={() => setOpen(false)} fans={FANS} />;
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
      expect(screen.getByText("Applies to all 2 models")).toBeInTheDocument();
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

    it("closes on no-op Save without a PUT", async () => {
      const user = userEvent.setup();
      relayMock.put.mockResolvedValue({});
      renderWithProviders(<AllHost />);
      await countSelect();
      await user.click(screen.getByRole("button", { name: "Save" }));
      await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
      expect(relayMock.put).not.toHaveBeenCalled();
    });

    it("Save PUTs once per Creator, each keeping its own moves, and closes", async () => {
      const user = userEvent.setup();
      rosterMock.rows = ROSTER;
      relayMock.put.mockImplementation((_path: string, body: { account_id: string; config: unknown }) =>
        Promise.resolve(body));
      renderWithProviders(<AllHost />);
      await user.selectOptions(await countSelect(), "2");
      await user.selectOptions(
        within(screen.getByRole("region", { name: "Chatters" })).getByRole("combobox", { name: "Fixture Chatter B" }),
        "Inbox 2",
      );
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(relayMock.put).toHaveBeenCalledTimes(2);
      expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
        account_id: ACCOUNT_ID,
        config: { group_count: 2, assignments: { "200000001": 2 }, chatter_groups: { "c-a": 1, "c-b": 2 } },
      });
      expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
        account_id: OTHER_ID,
        config: { group_count: 2, assignments: {}, chatter_groups: { "c-a": 2, "c-x": 1 } },
      });
      await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
    });

    it.each([false, true])("failed PUTs name affected Creators (all failed: %s)", async (allFailed) => {
      const user = userEvent.setup();
      relayMock.put.mockImplementation((_path: string, body: { account_id: string; config: unknown }) =>
        allFailed || body.account_id === OTHER_ID ? Promise.reject(new RelayError(502, null, "upstream down")) : Promise.resolve(body));
      renderWithProviders(<AllHost />);
      await user.selectOptions(await countSelect(), "4");
      await user.click(screen.getByRole("button", { name: "Save" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/Not saved for .*Fixture Creator Nine: upstream down\./);
      expect(alert).toHaveTextContent(/upstream down\.$|upstream down\. 1 model saved\.$/);
      expect(alert.textContent?.includes("1 model saved.")).toBe(!allFailed);
      expect(relayMock.put).toHaveBeenCalledTimes(2);
      expect(dialog()).toBeInTheDocument();
      expect(await countSelect()).toHaveValue("4");
    });
  });
});
