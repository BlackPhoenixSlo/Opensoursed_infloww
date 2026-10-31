/**
 * PPV row (seam 1: the `Composer`) — the send payload pinned before the
 * Phase 4 rebuild replaces the Composer's chrome (ticket 26). Every check
 * asserts at `onSend`; for the same inputs it must receive the same
 * `SendArgs` after the rebuild (spec, Contracts). A later ticket may change
 * how a test reaches a control, but not what it asserts.
 *
 * Ticket 30 opens the PPV row from the "PPV" pill and pins the row itself:
 * its children's order, the 42px tiles, and "Clear".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import {
  FIXTURE_MEDIA, expectDomOrder, pickSendAt, renderComposer, resetComposerHarness,
} from "./composerTestHarness";

beforeEach(() => resetComposerHarness());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function priceInputs() {
  return screen.getAllByRole("textbox", { name: "PPV price" }) as HTMLInputElement[];
}

const ppvPill = () =>
  within(screen.getByRole("toolbar", { name: "Composer buttons" })).getByRole("button", { name: "PPV" });
const ppvRow = () => screen.queryByRole("group", { name: "PPV row" });
/** The attachment tiles inside the PPV row, found by their ✕. */
const rowTiles = () =>
  within(screen.getByRole("group", { name: "PPV row" }))
    .getAllByRole("button", { name: "Remove attachment" })
    .map((x) => x.parentElement as HTMLElement);

describe("PPV row: the pill and the row", () => {
  it('the "PPV" pill toggles aria-pressed and the "PPV row"; the row holds PPV, $, lock text, at and Clear in order', async () => {
    const user = userEvent.setup();
    await renderComposer();

    expect(ppvPill()).toHaveAttribute("aria-pressed", "false");
    expect(ppvRow()).not.toBeInTheDocument();
    await user.click(ppvPill());
    expect(ppvPill()).toHaveAttribute("aria-pressed", "true");
    expect(ppvRow()).toBeInTheDocument();
    await user.click(ppvPill());
    expect(ppvPill()).toHaveAttribute("aria-pressed", "false");
    expect(ppvRow()).not.toBeInTheDocument();

    await user.click(ppvPill());
    await user.click(screen.getByRole("button", { description: "Schedule send for later" }));
    const row = within(ppvRow()!);
    expectDomOrder([
      row.getByText("PPV"),
      row.getByRole("textbox", { name: "PPV price" }),
      row.getByRole("checkbox", { name: "lock text" }),
      row.getByText("at"),
      row.getByRole("button", { name: "Clear" }),
    ]);
  });

  it("applyTemplate with a price and two media opens the row with two 42px tiles", async () => {
    const { api } = await renderComposer();

    act(() => api.current!.applyTemplate({
      source: "local", text: "Synthetic set", displayText: "Synthetic set", mediaCount: 2,
      price: 18, lockedText: false, isWelcome: false, media: FIXTURE_MEDIA,
      previews: [], taggedUsers: [],
    }));

    expect(ppvRow()).toBeInTheDocument();
    expect(priceInputs()[0].value).toBe("18");
    const tiles = rowTiles();
    expect(tiles).toHaveLength(2);
    for (const tile of tiles) expect(tile).toHaveClass("size-10.5");
  });

  it('while the row holds media the "PPV" pill is aria-disabled, says Clear closes it, and a click keeps the row', async () => {
    const user = userEvent.setup();
    await renderComposer();

    await user.click(screen.getByRole("button", { name: /vault/i }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
    expect(ppvPill()).toHaveAttribute("aria-disabled", "true");
    expect(ppvPill()).not.toBeDisabled(); // focus and hover still reach its title
    expect(ppvPill()).toHaveAttribute("title", expect.stringMatching(/Clear empties and closes it/));
    await user.click(ppvPill());
    expect(ppvRow()).toBeInTheDocument();
    expect(ppvPill()).toHaveAttribute("aria-pressed", "true");
  });

  it('"Clear" empties the row, keeps the text and hides the row', async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts'), "hi");
    await user.click(screen.getByRole("button", { name: /vault/i }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
    await user.click(screen.getByRole("checkbox", { name: "lock text" }));
    await user.click(screen.getByRole("button", { description: "Schedule send for later" }));
    await pickSendAt(user, 30);
    await user.click(screen.getByRole("button", { name: "More free previews" }));

    await user.click(within(ppvRow()!).getByRole("button", { name: "Clear" }));

    expect(ppvRow()).not.toBeInTheDocument();
    expect(ppvPill()).toHaveAttribute("aria-pressed", "false");
    expect((screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement).value).toBe("hi");
    await user.click(ppvPill());
    expect(priceInputs()[0].value).toBe("");
    expect(screen.getByRole("checkbox", { name: "lock text" })).not.toBeChecked();
    expect(within(ppvRow()!).queryByText("at")).not.toBeInTheDocument();
    expect(within(ppvRow()!).queryByRole("button", { name: "Remove attachment" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { description: "Schedule send for later" }));
    expect((screen.getByLabelText("Send at") as HTMLInputElement).value).toBe("");
    await user.click(screen.getByRole("button", { description: "Schedule send for later" }));

    // Re-picking the same media sends no previews, no lock and no schedule.
    await user.click(screen.getByRole("button", { name: /vault/i }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({
      text: "hi", price: 25, lockedText: false, attached: FIXTURE_MEDIA,
    });
  });
});

describe("PPV row: price and lock text", () => {
  it('"hi" at 12.5 with lock text ticked sends text, price and locked text; lock text starts unticked', async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    // Ticket 30: the price lives in the PPV row, opened by the "PPV" pill.
    await user.click(ppvPill());
    await user.type(priceInputs()[0], "12.5");
    const lock = screen.getByRole("checkbox", { name: "lock text" });
    expect(lock).not.toBeChecked();
    await user.click(lock);
    await user.type(screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts'), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "hi", price: 12.5, lockedText: true });
  });

  it("with an empty price the send carries no price", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts'), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend.mock.calls[0][0]).toEqual({ text: "hi" });
    expect(onSend.mock.calls[0][0]).not.toHaveProperty("price");
  });
});

describe("PPV row: vault media and free previews", () => {
  async function pickFixtureMedia(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: /vault/i }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
  }

  it("two picked media at $10 and $25 price the send at 25 and carry both in pick order", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await pickFixtureMedia(user);
    expect(ppvRow()).toBeInTheDocument();
    // Ticket 30: one price field; the per-tile inputs are gone.
    expect(priceInputs()).toHaveLength(1);
    expect(rowTiles()).toHaveLength(2);
    for (const input of priceInputs()) expect(Number(input.value)).toBe(25);
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    // Pick order is 9102 ($10) then 9101 ($25): sorted by neither id nor price.
    expect(onSend.mock.calls[0][0].attached?.map((m) => m.id)).toEqual([9102, 9101]);
    expect(onSend).toHaveBeenCalledWith({
      text: "", price: 25, lockedText: false, attached: FIXTURE_MEDIA,
    });
  });

  it("with one free preview the send carries the first media's id as the preview", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await pickFixtureMedia(user);
    // TODO.md A2: the stepper shows inline in the PPV row.
    await user.click(screen.getByRole("button", { name: "More free previews" }));
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend.mock.calls[0][0].attached?.map((m) => m.id)).toEqual([9102, 9101]);
    expect(onSend).toHaveBeenCalledWith({
      text: "", price: 25, lockedText: false, previews: [9102], attached: FIXTURE_MEDIA,
    });
  });
});

describe("PPV row: schedule", () => {
  it('a future "at" relabels Send to "Schedule" and the send carries scheduledAt', async () => {
    // Only Date is faked: the clock is frozen, user-event's timers stay real.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-13T10:00:00.000Z"));
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts'), "hi");
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { description: "Schedule send for later" }));
    // TODO.md A2: the "at" presets live under ⏱.
    await pickSendAt(user, 30);

    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    // The calendar icon is also named "Schedule" (ticket 27); Send is the one
    // whose tooltip is the keyboard hint.
    await user.click(screen.getByRole("button", {
      name: "Schedule", description: "Enter to send · Shift+Enter for newline",
    }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "hi", scheduledAt: "2026-10-13T10:30:00.000Z" });
  });
});

/* Look-and-feel ticket 148 (docs/spec/messages-pro-look-and-feel/
 * phase-05-composer.md, Gap row C11): the price field in Infloww's input
 * style, its `$` inside the 85px box 5px in, and the free-preview divider
 * under today's rule. */
describe("PPV row: Infloww's price field and the free-preview divider", () => {
  const DIVIDER = "Items left of this line are free previews; items right are PPV-locked";

  it('the price field is still named "PPV price" and its "$" is a prefix inside the field\'s 85px box, 5px in, radius 4px', async () => {
    const user = userEvent.setup();
    await renderComposer();

    await user.click(ppvPill());
    const price = priceInputs()[0];
    const box = price.parentElement as HTMLElement;
    // The box is the field: it draws the border and holds "$" before the input.
    expect(box.firstChild?.textContent).toBe("$");
    expect(box.textContent).toBe("$");
    expect(box.className.split(/\s+/)).toEqual(
      expect.arrayContaining(["w-21.25", "pl-1.25", "rounded-[4px]", "border"]));
    // The input inside draws no box of its own.
    expect(price.className.split(/\s+/)).not.toContain("border");
  });

  it("the divider shows only while the draft is priced with at least one free and one paid tile", async () => {
    const user = userEvent.setup();
    await renderComposer();

    await user.click(screen.getByRole("button", { name: /vault/i }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
    // Priced at 25, no free tile: no divider.
    expect(screen.queryByTitle(DIVIDER)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More free previews" }));
    // One free, one paid: the divider sits in the row between the two tiles.
    const divider = within(ppvRow()!).getByTitle(DIVIDER);
    const [free, paid] = rowTiles();
    expectDomOrder([free, divider, paid]);

    await user.click(screen.getByRole("button", { name: "More free previews" }));
    // Both free, none paid: no divider.
    expect(screen.queryByTitle(DIVIDER)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Fewer free previews" }));
    expect(screen.getByTitle(DIVIDER)).toBeInTheDocument();
    await user.clear(priceInputs()[0]);
    // Unpriced: no divider.
    expect(screen.queryByTitle(DIVIDER)).not.toBeInTheDocument();
  });
});
