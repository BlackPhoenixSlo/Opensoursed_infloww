/**
 * Lock text through the rendered Composer (seam 1): a send clears it, so the
 * next PPV goes out unlocked unless the chatter ticks it again, and a refused
 * schedule hands it back with the rest of the draft (composerDraft `sent` /
 * `restore`): its media and free previews too, or, when the chatter has typed
 * on since, as its own notice with Restore, which no later toast replaces
 * (`afterRefusedSchedule`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { resetSendGapForTests } from "@/lib/sendGuards";

import { pickSendAt, renderComposer, resetComposerHarness } from "./composerTestHarness";

beforeEach(() => resetComposerHarness());
afterEach(() => cleanup());

const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;
const ppvPill = () =>
  within(screen.getByRole("toolbar", { name: "Composer buttons" })).getByRole("button", { name: "PPV" });
const price = () => screen.getByRole("textbox", { name: "PPV price" }) as HTMLInputElement;
const lock = () => screen.getByRole("checkbox", { name: "lock text" });
const tiles = () => screen.queryAllByRole("button", { name: "Remove attachment" });
const previews = () => within(screen.getByRole("group", { name: "Free previews" }));
const restoreButtons = () => screen.queryAllByRole("button", { name: "Restore" });

/** Vault → the stub's fixture media ($10 and $25: the price becomes 25.00),
 *  then one free preview. */
async function attachWithPreview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Vault" }));
  await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
  await user.click(previews().getByRole("button", { name: "More free previews" }));
  expect(previews().getByText("1/2")).toBeInTheDocument();
}

describe("Composer: lock text", () => {
  it("a sent PPV's lock does not ride on to the next PPV", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.click(ppvPill());
    await user.type(price(), "5");
    await user.click(lock());
    await user.type(textbox(), "one{Enter}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend.mock.calls[0][0]).toEqual({ text: "one", price: 5, lockedText: true });

    resetSendGapForTests(); // the 3 s send-rate guard
    await user.click(ppvPill());
    expect(lock()).not.toBeChecked();
    await user.type(price(), "6");
    await user.type(textbox(), "two{Enter}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend.mock.calls[1][0]).toEqual({ text: "two", price: 6, lockedText: false });
  });

  it("a refused schedule restores the lock with the price and text", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();
    onSend.mockImplementationOnce(() => Promise.reject(new Error("relay said no")));

    await user.click(ppvPill());
    await user.type(price(), "5");
    await user.click(lock());
    await user.type(textbox(), "later");
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Enter}");

    expect(await screen.findByText(/Not scheduled — relay said no/)).toBeInTheDocument();
    expect(textbox().value).toBe("later");
    expect(price().value).toBe("5");
    expect(lock()).toBeChecked();
    expect(restoreButtons()).toHaveLength(0); // put back already: nothing to offer
  });

  it("a refused schedule hands back the media and free previews too", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();
    onSend.mockImplementationOnce(() => Promise.reject(new Error("relay said no")));

    await attachWithPreview(user);
    await user.type(textbox(), "later");
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Enter}");

    expect(await screen.findByText(/Not scheduled — relay said no/)).toBeInTheDocument();
    expect(onSend.mock.calls[0][0]).toMatchObject({ price: 25, previews: [9102] });
    expect(textbox().value).toBe("later");
    expect(tiles()).toHaveLength(2);
    expect(previews().getByText("1/2")).toBeInTheDocument();
    expect(price().value).toBe("25.00");
    expect(restoreButtons()).toHaveLength(0);
  });

  it("typed on while the schedule was in flight: the new draft stays; a later toast leaves the offer, whose Restore brings the refused one back", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 1 }); // an offer names a Fan's chat
    let refuse!: (err: Error) => void;
    onSend.mockImplementationOnce(() => new Promise<void>((_, reject) => { refuse = reject; }));

    await attachWithPreview(user);
    await user.type(textbox(), "later");
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(textbox().value).toBe("");

    await user.type(textbox(), "something else");
    await act(async () => refuse(new Error("relay said no")));

    expect(await screen.findByText(/Not scheduled — relay said no: “later”\. Restore replaces your current draft/)).toBeInTheDocument();
    expect(textbox().value).toBe("something else");
    expect(tiles()).toHaveLength(0);

    // The new draft schedules fine: its "Scheduled" toast does not replace the offer.
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Enter}");
    expect(await screen.findByText(/Scheduled · sending in/)).toBeInTheDocument();
    expect(onSend.mock.calls[1][0]).toMatchObject({ text: "something else" });
    expect(restoreButtons()).toHaveLength(1);

    await user.click(restoreButtons()[0]);
    expect(textbox().value).toBe("later");
    expect(tiles()).toHaveLength(2);
    expect(previews().getByText("1/2")).toBeInTheDocument();
    expect(price().value).toBe("25.00");
    expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();
  });

  it("two refused while typed on: both are offered, each restores its own draft", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 1 });
    const refusals: ((err: Error) => void)[] = [];
    const pending = () => new Promise<void>((_, reject) => { refusals.push(reject); });
    onSend.mockImplementationOnce(pending).mockImplementationOnce(pending);

    await attachWithPreview(user);
    await user.type(textbox(), "first");
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Enter}");
    await user.type(textbox(), "second");
    await pickSendAt(user, 10);
    await user.click(textbox());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    await user.type(textbox(), "third");
    await act(async () => refusals.forEach((r) => r(new Error("relay said no"))));

    expect(await screen.findByText(/“first”/)).toBeInTheDocument();
    expect(screen.getByText(/“second”/)).toBeInTheDocument();
    expect(textbox().value).toBe("third");
    expect(restoreButtons()).toHaveLength(2);

    await user.click(restoreButtons()[1]);
    expect(textbox().value).toBe("second");
    expect(tiles()).toHaveLength(0);
    await user.click(restoreButtons()[0]);
    expect(textbox().value).toBe("first");
    expect(tiles()).toHaveLength(2);
    expect(price().value).toBe("25.00");
    expect(restoreButtons()).toHaveLength(0);
  });
});
