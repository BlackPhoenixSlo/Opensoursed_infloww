/**
 * AI Copilot (the Composer's "AI" pill; Infloww help articles 262036/262040):
 * pick Casual / Re-engage / Tip request / Sexting → one request → three
 * suggestions; a pick goes into the text box and is never sent; Regenerate
 * sends the set on screen as `avoid`; a Relay error prints its sentence.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { relayPost, renderComposer, resetComposerHarness } from "./composerTestHarness";
import { RelayError } from "@/lib/relay";

beforeEach(() => resetComposerHarness());
afterEach(() => cleanup());

const textbox = () =>
  screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;

const suggestCalls = () =>
  relayPost.mock.calls.filter(([path]) => String(path).includes("/admin/copilot/"));

function answer(...sets: string[][]) {
  let i = 0;
  relayPost.mockImplementation((path: string, body?: unknown) =>
    String(path).includes("/admin/copilot/")
      ? Promise.resolve({ mode: (body as { mode: string }).mode, suggestions: sets[Math.min(i++, sets.length - 1)] })
      : Promise.resolve({}));
}

async function openCopilot(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    within(screen.getByRole("toolbar", { name: "Composer buttons" })).getByRole("button", { name: "AI" }),
  );
  return within(screen.getByRole("region", { name: "AI Copilot" }));
}

describe("CopilotPicker", () => {
  it("offers Infloww's four modes and no saved lines", async () => {
    const user = userEvent.setup();
    await renderComposer({ fanId: 42 });
    const panel = await openCopilot(user);
    const modes = within(panel.getByRole("group", { name: "Reply style" })).getAllByRole("button");
    expect(modes.map((b) => b.textContent)).toEqual(["Casual", "Re-engage", "Tip request", "Sexting"]);
    expect(screen.queryByText(/saved lines/i)).toBeNull();
    expect(suggestCalls()).toHaveLength(0); // opening costs nothing
  });

  it("picks a mode with one request and inserts a suggestion without sending", async () => {
    const user = userEvent.setup();
    answer(["hey you 😘", "miss me?", "what r u up to"]);
    const { onSend } = await renderComposer({ fanId: 42 });
    const panel = await openCopilot(user);
    await user.click(panel.getByRole("button", { name: "Re-engage" }));
    expect(await panel.findByRole("button", { name: "miss me?" })).toBeTruthy();
    expect(suggestCalls()).toEqual([
      ["/admin/copilot/acct-1/42/suggest", { mode: "reengage", avoid: [] }, { accountId: "acct-1" }],
    ]);
    // Re-picking the mode on screen does not pay for another call.
    await user.click(panel.getByRole("button", { name: "Re-engage" }));
    expect(suggestCalls()).toHaveLength(1);

    await user.click(panel.getByRole("button", { name: "miss me?" }));
    expect(textbox().value).toBe("miss me?");
    expect(screen.queryByRole("region", { name: "AI Copilot" })).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("regenerates the same mode, avoiding the set on screen", async () => {
    const user = userEvent.setup();
    answer(["a1", "a2", "a3"], ["b1", "b2", "b3"]);
    await renderComposer({ fanId: 42 });
    const panel = await openCopilot(user);
    await user.click(panel.getByRole("button", { name: "Sexting" }));
    await panel.findByRole("button", { name: "a1" });
    await user.click(panel.getByRole("button", { name: "Regenerate" }));
    expect(await panel.findByRole("button", { name: "b2" })).toBeTruthy();
    expect(suggestCalls()[1][1]).toEqual({ mode: "sexting", avoid: ["a1", "a2", "a3"] });
  });

  it("prints the Relay's sentence on a failure", async () => {
    const user = userEvent.setup();
    relayPost.mockImplementation(() =>
      Promise.reject(new RelayError(429, {}, "Today's AI limit for this creator is reached.")));
    await renderComposer({ fanId: 42 });
    const panel = await openCopilot(user);
    await user.click(panel.getByRole("button", { name: "Tip request" }));
    expect((await panel.findByRole("alert")).textContent).toBe(
      "Today's AI limit for this creator is reached.");
  });

  it("starts clean when the Fan changes", async () => {
    const user = userEvent.setup();
    answer(["for fan 42"]);
    const { rerender, onSend, api } = await renderComposer({ fanId: 42 });
    let panel = await openCopilot(user);
    await user.click(panel.getByRole("button", { name: "Casual" }));
    await panel.findByRole("button", { name: "for fan 42" });

    const { Composer } = await import("./Composer");
    rerender(<Composer accountId="acct-1" fanId={43} onSend={onSend} composerApiRef={api} />);
    panel = await openCopilot(user);
    expect(panel.queryByRole("button", { name: "for fan 42" })).toBeNull();
    expect(panel.getByText("Pick a style to get 3 replies for this chat.")).toBeTruthy();
    expect(suggestCalls()).toHaveLength(1);
  });
});
