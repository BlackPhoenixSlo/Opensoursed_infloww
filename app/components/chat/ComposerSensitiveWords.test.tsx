/**
 * Growth > Sensitive words in the Messages Pro Composer. As in Infloww's chat,
 * a draft holding a listed word shows "Input contains prohibited language:
 * [word]" above the text, and Send stays enabled (a warning, not a block).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { relayGet, renderComposer, resetComposerHarness, routeRelay } from "./composerTestHarness";

beforeEach(() => resetComposerHarness());
afterEach(() => cleanup());

const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts');

describe("Composer: Sensitive words", () => {
  it("warns on a listed word, for the chat's Creator, without blocking Send", async () => {
    routeRelay("/admin/sensitive-words", () => ({ words: ["venmo", "cash app"] }));
    const user = userEvent.setup();
    await renderComposer();

    await user.type(textbox(), "pay me on Venmo or Cash App");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Input contains prohibited language: [venmo][cash app]");
    expect(relayGet.mock.calls.some(([p]) => p === "/admin/sensitive-words?account_id=acct-1")).toBe(true);
    expect((screen.getByRole("button", { name: /^Send/ }) as HTMLButtonElement).disabled).toBe(false);

    await user.clear(textbox());
    await user.type(textbox(), "hi there");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
