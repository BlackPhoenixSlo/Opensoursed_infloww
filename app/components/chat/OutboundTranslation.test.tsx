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

  it("a failed translation says so and Retry asks again", async () => {
    localStorage.setItem(fanLanguageKey("acct-1", FAN), "de");
    let fail = true;
    relayPost.mockImplementation((path: string, body?: unknown) => Promise.resolve(
      path === "/admin/translate"
        ? { results: (body as { texts: string[] }).texts.map((t) => (fail ? null : { text: `[de] ${t}`, lang: "en" })) }
        : {},
    ));
    const user = userEvent.setup();
    await renderComposer({ fanId: FAN });

    await user.type(textbox(), "want to see");
    await waitFor(() => expect(screen.getByText("Translation failed.")).toBeInTheDocument(), SETTLE);
    expect(screen.getByRole("button", { name: "Send translation" })).toBeDisabled();

    fail = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("[de] want to see")).toBeInTheDocument(), SETTLE);
    expect(screen.queryByText("Translation failed.")).toBeNull();
  });
});
