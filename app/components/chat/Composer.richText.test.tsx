/**
 * Composer and a formatted script (OF rich text): the pick shows the "Formatted" preview and Enter sends the
 * script's markup; it survives a chat switch and back (lib/chatDrafts keeps it beside the draft text); an edit
 * sends plain text. The "Next in" bubble shows a formatted step as text, never its tags.
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

const HTML = '<p><strong><span class="m-editor-fc__blue-1">Hey</span></strong> babe</p><p>line two</p>';
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
const box = () => screen.getByPlaceholderText("Message fan…") as HTMLTextAreaElement;
async function pick() {
  fireEvent.click(screen.getByTitle("Insert saved template"));
  fireEvent.click(await screen.findByText("Rich"));
  await waitFor(() => expect(box().value).toBe("Hey babe\nline two"));
}
async function enter() {
  resetSendGapForTests();
  await act(async () => { fireEvent.keyDown(box(), { key: "Enter" }); });
  await waitFor(() => expect(onSend).toHaveBeenCalled());
}
const preview = () => document.querySelector("[data-rich-preview]");

describe("a formatted script in the chat composer", () => {
  it("picked: the preview shows and Enter sends its markup", async () => {
    await mount(7);
    await pick();
    expect(preview()!.querySelector("strong span.m-editor-fc__blue-1")!.textContent).toBe("Hey");
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe(HTML);
  });

  it("survives a chat switch and back: still formatted", async () => {
    const a = await mount(7);
    await pick();
    a.unmount();
    const b = await mount(8); // another chat: no markup there
    expect(preview()).toBeNull();
    b.unmount();
    await mount(7);
    await waitFor(() => expect(box().value).toBe("Hey babe\nline two"));
    expect(preview()).not.toBeNull();
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe(HTML);
  });

  it("edited: the hint shows and it sends plain text; a remount keeps it plain", async () => {
    const a = await mount(7);
    await pick();
    fireEvent.change(box(), { target: { value: "Hey babe!" } });
    expect(document.querySelector("[data-rich-dropped]")).not.toBeNull();
    a.unmount();
    await mount(7);
    await waitFor(() => expect(box().value).toBe("Hey babe!"));
    expect(preview()).toBeNull();
    await enter();
    expect(onSend.mock.calls[0][0].text).toBe("Hey babe!");
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
