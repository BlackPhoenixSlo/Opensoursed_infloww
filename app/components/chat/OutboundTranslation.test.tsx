/**
 * Outbound translation in the Messages Pro composer (04 M15/M16): Alt+T opens
 * the strip, the Fan's language is kept per Fan, and the draft's translation
 * can replace the draft or be sent as it is.
 *
 * The relay is mocked by URL (the Composer's Seam 1 harness).
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { fanLanguageKey } from "@/lib/fanLanguage";
import { resetSendGapForTests } from "@/lib/sendGuards";
import { relayPost, renderComposer, resetComposerHarness } from "./composerTestHarness";

const FAN = 200000001;
const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;
const strip = () => screen.queryByRole("region", { name: "Translate my message" });
/** Past the draft's 400 ms debounce, on a busy machine too. */
const SETTLE = { timeout: 5_000 };
const translateCalls = () => relayPost.mock.calls.filter(([path]) => path === "/admin/translate");

beforeEach(() => {
  resetComposerHarness();
  relayPost.mockImplementation((path: string, body?: unknown) => Promise.resolve(
    path === "/admin/translate"
      ? { results: (body as { texts: string[] }).texts.map((t) => ({ text: `[es] ${t}`, lang: "en" })) }
      : {},
  ));
});
afterEach(() => {
  cleanup();
  relayPost.mockReset();
  relayPost.mockImplementation(() => Promise.resolve({}));
});

describe("OutboundTranslation", () => {
  it("Alt+T opens the strip; the Fan's language is kept and the draft is translated into it; Use translation replaces the draft", async () => {
    const user = userEvent.setup();
    await renderComposer({ fanId: FAN });
    expect(strip()).toBeNull();

    await user.click(textbox());
    await user.keyboard("{Alt>}t{/Alt}");
    expect(strip()).not.toBeNull();
    await user.selectOptions(screen.getByRole("combobox", { name: "Translate into" }), "es");
    expect(localStorage.getItem(fanLanguageKey("acct-1", FAN))).toBe("es");

    await user.type(textbox(), "see you soon");
    await waitFor(() => expect(screen.getByText("[es] see you soon")).toBeInTheDocument(), SETTLE);
    expect(translateCalls().at(-1)).toEqual(["/admin/translate", { texts: ["see you soon"], target: "es" }, { accountId: "acct-1" }]);

    await user.click(screen.getByRole("button", { name: "Use translation" }));
    expect(textbox().value).toBe("[es] see you soon");

    // The Fan's language opens the strip by itself next time.
    cleanup();
    await renderComposer({ fanId: FAN });
    expect(strip()).not.toBeNull();
  });

  it("Send translation and Ctrl+Enter send the translation in place of the draft", async () => {
    localStorage.setItem(fanLanguageKey("acct-1", FAN), "es");
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: FAN });

    await user.type(textbox(), "hello");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send translation" })).toBeEnabled(), SETTLE);
    await user.click(screen.getByRole("button", { name: "Send translation" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend.mock.calls[0][0]).toEqual({ text: "[es] hello" });
    expect(textbox().value).toBe("");

    // A fresh composer, and no send behind it: the 3 s send-rate guard is
    // one clock for every composer and would hold a second send here.
    cleanup();
    resetSendGapForTests();
    const again = await renderComposer({ fanId: FAN });
    await user.type(textbox(), "bye");
    await waitFor(() => expect(screen.getByText("[es] bye")).toBeInTheDocument(), SETTLE);
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(again.onSend).toHaveBeenCalledTimes(1));
    expect(again.onSend.mock.calls[0][0]).toEqual({ text: "[es] bye" });
  });

  it("while the strip is open, Ctrl+Enter with no translation ready sends nothing (never the untranslated draft)", async () => {
    localStorage.setItem(fanLanguageKey("acct-1", FAN), "es");
    // The translation never arrives.
    relayPost.mockImplementation((path: string) => (path === "/admin/translate" ? new Promise(() => {}) : Promise.resolve({})));
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: FAN });

    await user.type(textbox(), "hello");
    await waitFor(() => expect(translateCalls()).toHaveLength(1), SETTLE);
    await user.keyboard("{Control>}{Enter}{/Control}");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onSend).not.toHaveBeenCalled();
    expect(textbox().value).toBe("hello");
  });

  it("the Translate popover's Translate my messages opens and closes the strip", async () => {
    const user = userEvent.setup();
    await renderComposer({ fanId: FAN });
    await user.click(screen.getByRole("button", { name: "Translate" }));
    await user.click(screen.getByRole("button", { name: "Translate my messages" }));
    expect(strip()).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Translate" }));
    await user.click(screen.getByRole("button", { name: "Translate my messages" }));
    expect(strip()).toBeNull();
  });
});
