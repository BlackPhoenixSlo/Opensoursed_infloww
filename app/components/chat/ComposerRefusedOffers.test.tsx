/**
 * A refused schedule through the rendered Composer (./refusedOffers): its
 * tags come back with the rest of the draft, one refused after a chat switch
 * is shown in every chat and restored, whole, in its own, and an identity
 * switch drops them all, a refusal landing after it included.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { pickSendAt, renderComposer, resetComposerHarness, routeRelay } from "./composerTestHarness";
import { relay } from "@/lib/relay";
import { clearRefusedOffers } from "./refusedOffers";

beforeEach(() => resetComposerHarness());
afterEach(() => cleanup());

const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;
const ppvPill = () =>
  within(screen.getByRole("toolbar", { name: "Composer buttons" })).getByRole("button", { name: "PPV" });
const price = () => screen.getByRole("textbox", { name: "PPV price" }) as HTMLInputElement;
const lock = () => screen.getByRole("checkbox", { name: "lock text" });
const restoreButtons = () => screen.queryAllByRole("button", { name: "Restore" });

const TAGGABLE = { id: 77, name: "Tagged Kim", user: { id: 77, name: "Tagged Kim", username: "kim" } };
const tagChip = () => screen.queryByRole("button", { name: "Remove Tagged Kim" });

async function tagKim(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Tag other Creators" }));
  await user.click(await screen.findByRole("button", { name: /Tagged Kim/ }));
  await user.click(screen.getByRole("button", { name: "Add" }));
  expect(tagChip()).toBeInTheDocument();
}

async function paidTaggedSchedule(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.click(ppvPill());
  await user.type(price(), "5");
  await user.click(lock());
  await tagKim(user);
  await user.type(textbox(), text);
  await pickSendAt(user, 5);
  await user.click(textbox());
  await user.keyboard("{Enter}");
}

/** Fan `fanId`'s chat, as ChatSurface keys it: a switch remounts. */
async function chats() {
  const { Composer } = await import("./Composer");
  const utils = await renderComposer({ fanId: 1, fanName: "Fan One" });
  const chat = (fanId: number) => (
    <Composer key={fanId} accountId="acct-1" fanId={fanId} fanName={`Fan ${fanId}`} onSend={utils.onSend} />
  );
  return { ...utils, chat };
}

/** The next send hangs until the returned `refuse` is called. */
function holdNextSend(onSend: Awaited<ReturnType<typeof renderComposer>>["onSend"]) {
  const box: { refuse?: (err: Error) => void } = {};
  onSend.mockImplementationOnce(() => new Promise<void>((_, reject) => { box.refuse = reject; }));
  return (err: Error) => box.refuse?.(err);
}

describe("Composer: a refused schedule's tags and chat", () => {
  beforeEach(() => routeRelay("/posts/tagged-friend-users", () => ({ items: [TAGGABLE], hasMore: false })));

  it("put straight back, the tags come with it", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 1 });
    onSend.mockImplementationOnce(() => Promise.reject(new Error("relay said no")));

    await paidTaggedSchedule(user, "later");

    expect(await screen.findByText(/Not scheduled — relay said no/)).toBeInTheDocument();
    expect(onSend.mock.calls[0][0]).toMatchObject({ text: "later", price: 5, taggedUsers: [77] });
    expect(textbox().value).toBe("later");
    expect(tagChip()).toBeInTheDocument();
  });

  it("offered beside a typed-on draft, Restore brings the tags back", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 1 });
    const refuse = holdNextSend(onSend);

    await paidTaggedSchedule(user, "later");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(tagChip()).not.toBeInTheDocument();
    await user.type(textbox(), "typed on");
    await act(async () => refuse(new Error("relay said no")));

    await user.click(await screen.findByRole("button", { name: "Restore" }));
    expect(textbox().value).toBe("later");
    expect(tagChip()).toBeInTheDocument();
    expect(price().value).toBe("5");
  });

  it("refused after a chat switch: shown in the other chat, without ✕, and restored whole in its own", async () => {
    const user = userEvent.setup();
    const { onSend, rerender, chat } = await chats();
    const refuse = holdNextSend(onSend);

    await paidTaggedSchedule(user, "later");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    rerender(chat(2)); // the chatter opens another Fan's chat
    await act(async () => refuse(new Error("relay said no")));

    expect(await screen.findByText(/Not scheduled in the chat with Fan One — relay said no: “later”\. Open that chat to restore it/))
      .toBeInTheDocument();
    expect(restoreButtons()).toHaveLength(0);
    // Its draft is not shown here, so it cannot be dismissed unseen.
    expect(screen.queryByRole("button", { name: "✕" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("Dismiss the refused message")).not.toBeInTheDocument();
    expect(textbox().value).toBe("");

    rerender(chat(1)); // back in the chat it was written in
    expect(screen.getByTitle("Dismiss the refused message")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Restore" }));
    expect(textbox().value).toBe("later");
    expect(price().value).toBe("5");
    expect(lock()).toBeChecked();
    expect(tagChip()).toBeInTheDocument();
    expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();

    rerender(chat(2)); // restored: gone from every chat
    expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();
  });

  it("an identity switch (clearRefusedOffers) drops the offer from every chat", async () => {
    const user = userEvent.setup();
    const { onSend, rerender, chat } = await chats();
    const refuse = holdNextSend(onSend);

    await paidTaggedSchedule(user, "later");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    await user.type(textbox(), "typed on");
    await act(async () => refuse(new Error("relay said no")));
    expect(await screen.findByRole("button", { name: "Restore" })).toBeInTheDocument();
    rerender(chat(2));
    expect(screen.getByText(/Not scheduled in the chat with Fan One/)).toBeInTheDocument();

    act(() => clearRefusedOffers());
    expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();
    rerender(chat(1));
    expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();
    expect(textbox().value).toBe("typed on");
  });

  it("a refusal landing after an identity switch is not offered to the new identity", async () => {
    const user = userEvent.setup();
    const { onSend, rerender, chat } = await chats();
    const refuse = holdNextSend(onSend);

    await paidTaggedSchedule(user, "later");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    rerender(chat(2));
    act(() => clearRefusedOffers()); // the identity switches while it is in flight
    await act(async () => refuse(new Error("relay said no")));

    expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();
    rerender(chat(1));
    expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();
  });

  it("a refusal dropped after an identity switch revokes its media's blob previews", async () => {
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL: vi.fn((f: Blob) => `blob:${(f as File).name}`), revokeObjectURL });
    vi.mocked(relay.uploadFile).mockResolvedValue({ ready: true, deduped: false, vault_id: 31, send_with: [31] });
    try {
      const user = userEvent.setup();
      const { onSend, rerender, chat } = await chats();
      const refuse = holdNextSend(onSend);

      await user.upload(screen.getByLabelText("Upload from computer"), new File(["x"], "a.png", { type: "image/png" }));
      await waitFor(() => expect(screen.queryByText(/uploading/i)).not.toBeInTheDocument());
      await user.type(textbox(), "later");
      await pickSendAt(user, 5);
      await user.click(textbox());
      await user.keyboard("{Enter}");
      await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
      expect(onSend.mock.calls[0][0].attached?.[0]?._localPreview).toBe("blob:a.png");
      rerender(chat(2));
      act(() => clearRefusedOffers()); // the identity switches while it is in flight
      expect(revokeObjectURL).not.toHaveBeenCalledWith("blob:a.png");
      await act(async () => refuse(new Error("relay said no")));

      expect(screen.queryByText(/Not scheduled/)).not.toBeInTheDocument();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:a.png");
    } finally {
      delete (URL as { createObjectURL?: unknown }).createObjectURL;
      delete (URL as { revokeObjectURL?: unknown }).revokeObjectURL;
    }
  });
});
