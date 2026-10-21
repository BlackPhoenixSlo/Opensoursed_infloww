/**
 * Infloww's composer guards in the Messages Pro Composer (gap 04 P7 and M27):
 * a price above free and under $3 reads "Minimum $3 USD or free" above the
 * input and holds Send, and a second send at once within 3 s stays in the
 * composer with OF's reason.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { renderComposer, resetComposerHarness } from "./composerTestHarness";

beforeEach(() => resetComposerHarness());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;
const sendButton = () => screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;

describe("Composer: send guards", () => {
  it("a price under $3 says \"Minimum $3 USD or free\" and holds Send; $3 or free sends", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 501 });
    await user.type(textbox(), "unlock me");
    await user.click(screen.getByRole("button", { name: "PPV" }));
    const [price] = screen.getAllByRole("textbox", { name: "PPV price" });

    await user.type(price, "2.5");
    expect(screen.getByRole("alert").textContent).toBe("⚠ Minimum $3 USD or free");
    expect(sendButton().disabled).toBe(true);
    await user.type(textbox(), "{Enter}");
    expect(onSend).not.toHaveBeenCalled();

    await user.clear(price);
    await user.type(price, "3");
    expect(screen.queryByRole("alert")).toBeNull();
    await user.click(sendButton());
    await waitFor(() => expect(onSend).toHaveBeenCalledWith({ text: "unlock me", price: 3, lockedText: false }));
  });

  it("a send within 3 s of the last stays in the composer with OF's reason; after 3 s it goes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onSend } = await renderComposer({ fanId: 501 });

    await user.type(textbox(), "one{Enter}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    await user.type(textbox(), "two{Enter}");
    expect(await screen.findByText(/OnlyFans does not allow sending too many messages at once\. Wait 3 seconds/)).toBeInTheDocument();
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(textbox().value).toBe("two");

    vi.advanceTimersByTime(3000);
    await user.type(textbox(), "{Enter}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend).toHaveBeenLastCalledWith({ text: "two" });
  });
});
