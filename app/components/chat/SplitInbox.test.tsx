/**
 * SplitInbox — the Split Inbox dialog, tested at its props with the relay
 * mocked by URL (docs/spec/phase-02-fan-list-pane.md, Testing Decisions;
 * tickets 102 and 104). A host owns `open` as FanList does, so "the dialog
 * closes" and "the dialog stays open" are what the Employee sees.
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { RelayError } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { SplitInbox, groupOf } from "./SplitInbox";

const relayMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: relayMock,
}));

const ACCOUNT_ID = "100000001";
/** A Creator split three ways, with one Fan moved by hand. */
const STORED = { group_count: 3, assignments: { "200000001": 2 } };
/** The Fans the Fan List has loaded, in its order, as it passes them in. */
const FANS = [
  { id: 200000001, name: "Fixture Fan One" },
  { id: 200000002, name: "Fixture Fan Two" },
  { id: 200000003, name: "Fixture Fan Three" },
];
/** The split the mocked relay answers with; STORED unless a case serves another. */
let stored: { group_count: number; assignments: Record<string, number> } = STORED;

function Host() {
  const [open, setOpen] = useState(true);
  return <SplitInbox accountId={ACCOUNT_ID} open={open} onClose={() => setOpen(false)} fans={FANS} />;
}

const dialog = () => screen.queryByRole("dialog", { name: "Split Inbox settings" });
const countSelect = async () =>
  within((await screen.findByRole("dialog", { name: "Split Inbox settings" })))
    .findByRole("combobox", { name: "Choose the number of groups" });

/** A Fan's group select in the reassign section, named by the Fan. */
const fanSelect = (name: string) =>
  within(screen.getByRole("region", { name: "Reassign fans to different groups" })).getByRole("combobox", { name });
const optionsOf = (select: HTMLElement) => within(select).getAllByRole("option").map((o) => o.textContent);

beforeEach(() => {
  stored = STORED;
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
      config: { group_count: 5, assignments: { "200000001": 2 } },
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
    // Nothing is applied: the choice stays, ready to retry.
    expect(await countSelect()).toHaveValue("2");
  });

  it("reassigning one Fan changes only that Fan's entry in the PUT body", async () => {
    const user = userEvent.setup();
    relayMock.put.mockImplementation((_path: string, body: { config: unknown }) =>
      Promise.resolve({ account_id: ACCOUNT_ID, ...body }));
    renderWithProviders(<Host />);
    const count = await countSelect();
    // One group: nowhere to move a Fan, so no reassign section.
    await user.selectOptions(count, "1");
    expect(screen.queryByRole("region", { name: "Reassign fans to different groups" })).not.toBeInTheDocument();

    // A count not saved yet: every Fan's select offers its groups, in Fan List order.
    await user.selectOptions(count, "4");
    const region = screen.getByRole("region", { name: "Reassign fans to different groups" });
    expect(within(region).getAllByRole("combobox").map((s) => s.getAttribute("aria-label")))
      .toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
    expect(optionsOf(fanSelect("Fixture Fan Two"))).toEqual(["Inbox 1", "Inbox 2", "Inbox 3", "Inbox 4"]);
    // Fan One shows the group it was moved to.
    expect(fanSelect("Fixture Fan One")).toHaveValue("2");

    // Move Fan Two to a group other than the one it shows.
    const shown = (fanSelect("Fixture Fan Two") as HTMLSelectElement).value;
    const moveTo = shown === "1" ? "2" : "1";
    await user.selectOptions(fanSelect("Fixture Fan Two"), `Inbox ${moveTo}`);
    expect(fanSelect("Fixture Fan Two")).toHaveValue(moveTo);
    await user.click(screen.getByRole("button", { name: "Save" }));

    // One PUT: the count, Fan One's stored move, Fan Two's new one, and nothing for Fan Three.
    expect(relayMock.put).toHaveBeenCalledTimes(1);
    expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 4, assignments: { "200000001": 2, "200000002": Number(moveTo) } },
    });
    await vi.waitFor(() => expect(dialog()).not.toBeInTheDocument());
  });

  it("lowering N drops the out-of-range assignments from the PUT body and keeps the in-range ones", async () => {
    const user = userEvent.setup();
    // Fan One moved to Inbox 2, Fan Two to Inbox 3.
    stored = { group_count: 3, assignments: { "200000001": 2, "200000002": 3 } };
    relayMock.put.mockImplementation((_path: string, body: { config: unknown }) =>
      Promise.resolve({ account_id: ACCOUNT_ID, ...body }));
    renderWithProviders(<Host />);
    await user.selectOptions(await countSelect(), "2");
    // Inbox 3 is gone from every Fan's select.
    expect(optionsOf(fanSelect("Fixture Fan Two"))).toEqual(["Inbox 1", "Inbox 2"]);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(relayMock.put).toHaveBeenCalledTimes(1);
    expect(relayMock.put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 2, assignments: { "200000001": 2 } },
    });
  });
});

describe("groupOf", () => {
  /** Sixty invented Fan ids, as OF sends them (numbers). */
  const FAN_IDS = Array.from({ length: 60 }, (_, i) => 200000001 + i);
  const split = (group_count: number, assignments: Record<string, number> = {}) => ({ group_count, assignments });

  it("is stable for the same id and always within 1..N, and a new split spreads the Fans over every group", () => {
    for (let n = 1; n <= 9; n++) {
      for (const id of FAN_IDS) {
        const group = groupOf(id, split(n));
        expect(group).toBe(groupOf(id, split(n)));
        // The id as text names the same Fan, so the same group.
        expect(groupOf(String(id), split(n))).toBe(group);
        expect(Number.isInteger(group) && group >= 1 && group <= n).toBe(true);
      }
    }
    // Every Fan belongs to one group at once, and no group of three is left empty (story 51).
    expect(new Set(FAN_IDS.map((id) => groupOf(id, split(3))))).toEqual(new Set([1, 2, 3]));
  });

  it("honours an explicit assignment within range, and ignores one out of range", () => {
    const id = FAN_IDS[0];
    expect([1, 2, 3].map((g) => groupOf(id, split(3, { [String(id)]: g })))).toEqual([1, 2, 3]);
    // Out of range: the Fan falls back to the group the split alone gives.
    const unassigned = groupOf(id, split(3));
    expect(groupOf(id, split(3, { [String(id)]: 4 }))).toBe(unassigned);
    expect(groupOf(id, split(3, { [String(id)]: 0 }))).toBe(unassigned);
    // Another Fan's move does not touch this one.
    expect(groupOf(id, split(3, { [String(FAN_IDS[1])]: 2 }))).toBe(unassigned);
  });

  it("hashes a 19-digit string id without losing precision", () => {
    // Ten ids that differ only in their last digits: as JavaScript numbers
    // they are all the same double, so only their text tells them apart.
    const ids = Array.from({ length: 10 }, (_, i) => `123456789012345670${i}`);
    expect(new Set(ids.map(Number)).size).toBe(1);

    expect(new Set(ids.map((id) => groupOf(id, split(9)))).size).toBeGreaterThan(1);
    // An explicit move is found by the id's exact text.
    const moved = split(9, { [ids[3]]: 7 });
    expect(groupOf(ids[3], moved)).toBe(7);
    expect(ids.filter((id) => id !== ids[3]).map((id) => groupOf(id, moved)))
      .toEqual(ids.filter((id) => id !== ids[3]).map((id) => groupOf(id, split(9))));
  });
});
