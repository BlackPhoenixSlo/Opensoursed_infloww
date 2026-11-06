/**
 * Composer and OF rich text: a picked formatted script opens in the rich editor (no second preview) and Enter sends
 * its markup; it survives a chat switch and back (lib/chatDrafts keeps it beside the draft text); "Aa" toggles the
 * formatting toolbar; plain text stays in the textarea, byte-identical; a Fansly account never gets markup. The "Next in" bubble shows a formatted step as text, never its tags.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { resetComposerHarness, routeRelay } from "./composerTestHarness";
import type { SavedReply } from "@/lib/relay";
import { resetSendGapForTests } from "@/lib/sendGuards";
import { renderWithProviders } from "@/test-utils";
import { PLATFORM_KEY, resetPlatformForTests, setPlatform } from "@/lib/platform";

const HTML = '<p><span class="m-editor-fc__blue-1"><strong>Hey</strong></span> babe</p><p>line two</p>';
const row = (id: number, text: string, over: Partial<SavedReply> = {}): SavedReply => ({
  id, account_id: "acc", title: "Rich", text, price: 0, locked_text: false, media: [],
  script_id: null, script_step: null, ...over,
});

let saved: SavedReply[];
const onSend = vi.fn(async (_a: { text: string }): Promise<undefined> => undefined);
beforeEach(() => {
  resetComposerHarness();
  window.sessionStorage.clear();
  window.localStorage.setItem("chatterly:lockedText-default-changed-seen", "1");
  saved = [row(1, HTML)];
  routeRelay("/admin/saved-replies", () => ({ list: saved }));
});
afterEach(() => { cleanup(); onSend.mockClear(); });

async function mount(fanId: number) {
  const { Composer } = await import("./Composer");
  return renderWithProviders(<Composer accountId="acc" fanId={fanId} onSend={onSend}
    placeholder="Message fan…" />);
}
const box = () => screen.getByPlaceholderText("Message fan…") as HTMLElement;
const boxText = () => { const b = box(); return b instanceof HTMLTextAreaElement ? b.value : b.innerText ?? b.textContent; };
async function pick() {
  fireEvent.click(screen.getByTitle("Insert saved template"));
  fireEvent.click(await screen.findByText("Rich"));
}
async function enter() {
  resetSendGapForTests();
  await act(async () => { fireEvent.keyDown(box(), { key: "Enter" }); });
  await waitFor(() => expect(onSend).toHaveBeenCalled());
}
const formatted = () => box().querySelector("span.m-editor-fc__blue-1 strong");
const aa = () => screen.queryByRole("button", { name: "Aa" });
const fmtBar = () => screen.queryByRole("toolbar", { name: "Text formatting" });

describe("a formatted script in the chat composer", () => {
  afterEach(() => { window.localStorage.removeItem(PLATFORM_KEY); resetPlatformForTests(); });

  it("picked: the box is the rich editor showing it formatted, no duplicate preview, and Enter sends its markup", async () => {
    await mount(7);
    await pick();
    await waitFor(() => expect(formatted()?.textContent).toBe("Hey"));
    expect(box().isContentEditable || box().getAttribute("contenteditable")).toBeTruthy();
    expect(document.querySelector("[data-rich-preview]")).toBeNull();
    expect(fmtBar()).toBeNull(); // "Aa" still off: formatted text, toolbar hidden (OF)
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe(HTML);
  });

  it("survives a chat switch and back: still formatted", async () => {
    const a = await mount(7);
    await pick();
    await waitFor(() => expect(formatted()).not.toBeNull());
    a.unmount();
    const b = await mount(8); // another chat: no markup there
    expect(box()).toBeInstanceOf(HTMLTextAreaElement);
    b.unmount();
    await mount(7);
    await waitFor(() => expect(formatted()?.textContent).toBe("Hey"));
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe(HTML);
  });

  it('"Aa" shows the toolbar in the rich editor; off again with no formatting the plain textarea is back', async () => {
    await mount(7);
    expect(box()).toBeInstanceOf(HTMLTextAreaElement);
    expect(aa()).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(aa()!);
    await waitFor(() => expect(fmtBar()).not.toBeNull());
    expect(aa()).toHaveAttribute("aria-pressed", "true");
    expect(box()).not.toBeInstanceOf(HTMLTextAreaElement);
    fireEvent.click(aa()!);
    await waitFor(() => expect(fmtBar()).toBeNull());
    expect(box()).toBeInstanceOf(HTMLTextAreaElement);
  });

  it('"Aa" off with formatting present: the toolbar hides, the formatting stays and is sent', async () => {
    await mount(7);
    fireEvent.click(aa()!);
    await pick();
    await waitFor(() => expect(formatted()).not.toBeNull());
    fireEvent.click(aa()!);
    await waitFor(() => expect(fmtBar()).toBeNull());
    expect(formatted()).not.toBeNull();
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe(HTML);
  });

  it("a plain typed message stays in the textarea and goes out byte-identical", async () => {
    await mount(7);
    fireEvent.change(box(), { target: { value: "hi <3 & co" } });
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe("hi <3 & co");
  });

  it("Fansly: no Aa, no toolbar, and a picked formatted script goes in as its plain text", async () => {
    setPlatform("fansly");
    await mount(7);
    expect(aa()).toBeNull();
    await pick();
    await waitFor(() => expect(boxText()).toBe("Hey babe\nline two"));
    expect(box()).toBeInstanceOf(HTMLTextAreaElement);
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe("Hey babe\nline two");
  });

  it("the Next in bubble shows a formatted step as text, never its tags", async () => {
    saved = [
      row(1, "step one", { title: null, script_id: "Promo", script_step: 1 }),
      row(2, HTML, { title: null, script_id: "Promo", script_step: 2 }),
    ];
    window.localStorage.setItem("chatterly:scriptCursor:acc:7", JSON.stringify({ scriptId: "Promo", step: 1 }));
    await mount(7);
    const bubble = await screen.findByTitle("Tap to load this step into the composer");
    await waitFor(() => expect(bubble.textContent).toContain("Hey babe line two"));
    expect(bubble.textContent).not.toContain("<p>");
  });
});
