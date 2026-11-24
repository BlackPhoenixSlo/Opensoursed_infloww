import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { renderComposer, resetComposerHarness } from "./composerTestHarness";
import { relay } from "@/lib/relay";

beforeEach(() => resetComposerHarness());
afterEach(() => cleanup());

const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;
const clearButton = () => screen.queryByRole("button", { name: "Clear message" });

describe("Composer: Clear beside Send", () => {
  it("shows only with a draft; empties text and PPV row, sends nothing", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 501 });
    expect(clearButton()).toBeNull();

    await user.type(textbox(), "wiqoefwelnfwejlfn");
    await user.click(screen.getByRole("button", { name: "PPV" }));
    const [price] = screen.getAllByRole("textbox", { name: "PPV price" });
    await user.type(price, "5");
    await user.click(clearButton()!);

    expect(textbox().value).toBe("");
    expect(screen.queryAllByRole("textbox", { name: "PPV price" })).toHaveLength(0);
    expect(clearButton()).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(textbox());
  });
  it("clears a quote-only draft through the parent callback", async () => {
    const onClearQuoted = vi.fn();
    const { onSend } = await renderComposer({
      quoted: { messageId: 7, preview: "original", authorName: "Fan" },
      onClearQuoted,
    });
    await userEvent.click(clearButton()!);
    expect(onClearQuoted).toHaveBeenCalledOnce();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("Clear cancels an upload-only draft", async () => {
    const user = userEvent.setup();
    const upload = vi.mocked(relay.uploadFile);
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:clear-upload");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL");
    let finish!: (value: Awaited<ReturnType<typeof relay.uploadFile>>) => void;
    upload.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { onSend } = await renderComposer({ fanId: 502 });
    try {
      await user.upload(screen.getByLabelText("Upload from computer"), new File(["x"], "clear.png", { type: "image/png" }));
      await waitFor(() => expect(finish).toBeTypeOf("function"));
      expect(clearButton()).not.toBeNull();
      await user.click(clearButton()!);
      expect(clearButton()).toBeNull();
      expect(onSend).not.toHaveBeenCalled();
      expect(revokeUrl).toHaveBeenCalledWith("blob:clear-upload");
    } finally {
      finish?.({ ready: true, deduped: false, vault_id: 9, send_with: [9] });
      createUrl.mockRestore();
      revokeUrl.mockRestore();
    }
  });

  it("Clear reopens slash search for the same pasted query", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();
    await user.type(textbox(), "/promo");
    await user.keyboard("{Escape}");
    await user.click(clearButton()!);
    fireEvent.change(textbox(), { target: { value: "/promo" } });
    await user.keyboard("{Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });
});
