/**
 * The Composer with queue keys (`onAdvance` / `onHoldChange`): Enter sends and
 * stays; ⌘/Ctrl+Enter sends, then moves to the next Fan — the translation
 * while the strip is open — but not from the "/" list, an empty composer, or
 * a send the 3 s guard holds (one clock per model, shared by its composers). Arrows move from
 * an empty composer, ⌘/Ctrl+arrows over a text draft, never over media or a
 * price (the per-Fan draft keeps only the text).
 *
 * The relay is mocked by URL (the Composer's Seam 1 harness).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { fanLanguageKey } from "@/lib/fanLanguage";
import { pickSendAt, relayPost, renderComposer, resetComposerHarness } from "./composerTestHarness";

const FAN = 200000001;
const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;

beforeEach(() => resetComposerHarness());
afterEach(() => {
  cleanup();
  relayPost.mockReset();
  relayPost.mockImplementation(() => Promise.resolve({}));
});

async function renderFocusComposer() {
  const log: string[] = [];
  const onAdvance = vi.fn((dir: 1 | -1) => { log.push(`advance ${dir}`); });
  const onHoldChange = vi.fn();
  const r = await renderComposer({ fanId: FAN, onAdvance, onHoldChange });
  r.onSend.mockImplementation(async (args) => { log.push(`send ${args.text}`); });
  return { ...r, onAdvance, onHoldChange, log };
}

describe("Composer queue keys: send keys", () => {
  it("Enter sends and stays; ⌘+Enter and Ctrl+Enter send, then move to the next Fan", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const { onAdvance, log } = await renderFocusComposer();

      await user.type(textbox(), "one{Enter}");
      await waitFor(() => expect(log).toEqual(["send one"]));
      expect(onAdvance).not.toHaveBeenCalled();

      vi.advanceTimersByTime(3000);
      await user.type(textbox(), "two");
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      // The send begins first (the parent marks it in flight), then the move.
      await waitFor(() => expect(log).toEqual(["send one", "send two", "advance 1"]));

      vi.advanceTimersByTime(3000);
      await user.type(textbox(), "three");
      await user.keyboard("{Control>}{Enter}{/Control}");
      await waitFor(() => expect(log.slice(3)).toEqual(["send three", "advance 1"]));
    } finally {
      vi.useRealTimers();
    }
  });

  it("⌘+Enter from an empty composer or the open \"/\" list sends nothing and stays", async () => {
    const user = userEvent.setup();
    const { onSend, onAdvance } = await renderFocusComposer();

    await user.click(textbox());
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await user.type(textbox(), "/hi");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onSend).not.toHaveBeenCalled();
    expect(onAdvance).not.toHaveBeenCalled();
  });

  it("a ⌘+Enter the 3 s guard holds stays on the Fan — the guard carries over from another Fan's composer", async () => {
    const user = userEvent.setup();
    const first = await renderComposer({ fanId: FAN + 1 });
    await user.type(textbox(), "to him{Enter}");
    await waitFor(() => expect(first.onSend).toHaveBeenCalledTimes(1));
    cleanup();

    const { onSend, onAdvance } = await renderFocusComposer();
    await user.type(textbox(), "to her");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(await screen.findByText(/Wait 3 seconds/)).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
    expect(onAdvance).not.toHaveBeenCalled();
    expect(textbox().value).toBe("to her");
  });

  it("the 3 s guard is per model: a send from another model's composer doesn't hold this one", async () => {
    const user = userEvent.setup();
    const other = await renderComposer({ accountId: "acct-2", fanId: FAN + 1 });
    await user.type(textbox(), "to him{Enter}");
    await waitFor(() => expect(other.onSend).toHaveBeenCalledTimes(1));
    cleanup();

    const { onSend, onAdvance } = await renderFocusComposer();
    await user.type(textbox(), "to her");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onAdvance).toHaveBeenCalledWith(1);
    expect(screen.queryByText(/Wait 3 seconds/)).not.toBeInTheDocument();
  });

  it("a scheduled ⌘+Enter moves on once it is enqueued; a refused one stays, restored", async () => {
    const user = userEvent.setup();
    const { onSend, onAdvance } = await renderFocusComposer();

    onSend.mockImplementationOnce(() => Promise.reject(new Error("relay said no")));
    await user.type(textbox(), "later");
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(await screen.findByText(/Not scheduled — relay said no/)).toBeInTheDocument();
    expect(onAdvance).not.toHaveBeenCalled();
    expect(textbox().value).toBe("later");

    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(onAdvance).toHaveBeenCalledWith(1));
    expect(onSend).toHaveBeenCalledTimes(2);
    expect(onSend.mock.calls[1][0].scheduledAt).toBeTruthy();
  });

  it("a scheduled ⌘+Enter that settles after the chatter moved on, or the composer unmounted, doesn't move", async () => {
    const user = userEvent.setup();
    const { Composer } = await import("./Composer");
    const { onSend, onAdvance, rerender, unmount } = await renderFocusComposer();
    let enqueue = () => {};
    onSend.mockImplementation(() => new Promise<void>((res) => { enqueue = res; }));

    await user.type(textbox(), "later");
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    // The chatter stepped to another Fan (same mount) before it was enqueued.
    rerender(<Composer accountId="acct-1" fanId={FAN + 7} onSend={onSend} onAdvance={onAdvance} />);
    enqueue();
    await new Promise((r) => setTimeout(r, 0));
    expect(onAdvance).not.toHaveBeenCalled();

    // Back on the first Fan: a second scheduled send, then the composer goes.
    rerender(<Composer accountId="acct-1" fanId={FAN} onSend={onSend} onAdvance={onAdvance} />);
    await user.type(textbox(), "later again");
    await pickSendAt(user, 5);
    await user.click(textbox());
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    unmount();
    enqueue();
    await new Promise((r) => setTimeout(r, 0));
    expect(onAdvance).not.toHaveBeenCalled();
  });

  it("with the translation strip open ⌘+Enter sends the translation, then moves on; its Send translation button stays", async () => {
    localStorage.setItem(fanLanguageKey("acct-1", FAN), "es");
    relayPost.mockImplementation((path: string, body?: unknown) => Promise.resolve(
      path === "/admin/translate"
        ? { results: (body as { texts: string[] }).texts.map((t) => ({ text: `[es] ${t}`, lang: "en" })) }
        : {},
    ));
    const user = userEvent.setup();
    const { onAdvance, log } = await renderFocusComposer();

    await user.type(textbox(), "hello");
    await waitFor(() => expect(screen.getByText("[es] hello")).toBeInTheDocument(), { timeout: 5_000 });
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(log).toEqual(["send [es] hello", "advance 1"]));
    expect(onAdvance).toHaveBeenCalledTimes(1);
  });
});

describe("Composer queue keys: arrows and held drafts", () => {
  it("→ / ← move from an empty composer; over text only with ⌘/Ctrl", async () => {
    const user = userEvent.setup();
    const { onAdvance } = await renderFocusComposer();

    await user.click(textbox());
    await user.keyboard("{ArrowRight}");
    await user.keyboard("{ArrowLeft}");
    expect(onAdvance.mock.calls).toEqual([[1], [-1]]);

    await user.type(textbox(), "draft");
    await user.keyboard("{ArrowLeft}");
    expect(onAdvance).toHaveBeenCalledTimes(2);
    await user.keyboard("{Meta>}{ArrowRight}{/Meta}");
    await user.keyboard("{Control>}{ArrowLeft}{/Control}");
    expect(onAdvance.mock.calls.slice(2)).toEqual([[1], [-1]]);
  });

  it("a price holds the draft: reported, and no arrow moves away from it", async () => {
    const user = userEvent.setup();
    const { onAdvance, onHoldChange, unmount } = await renderFocusComposer();
    expect(onHoldChange).toHaveBeenLastCalledWith(false);

    await user.type(textbox(), "unlock me");
    await user.click(screen.getByRole("button", { name: "PPV" }));
    const [price] = screen.getAllByRole("textbox", { name: "PPV price" });
    await user.type(price, "5");
    expect(onHoldChange).toHaveBeenLastCalledWith(true);

    await user.click(textbox());
    await user.keyboard("{Meta>}{ArrowRight}{/Meta}");
    expect(onAdvance).not.toHaveBeenCalled();

    unmount();
    expect(onHoldChange).toHaveBeenLastCalledWith(false);
  });

  it("without onAdvance the keys don't move: ⌘+Enter just sends", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: FAN });
    await user.type(textbox(), "hi");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(onSend).toHaveBeenCalledWith({ text: "hi" }));
  });
});
