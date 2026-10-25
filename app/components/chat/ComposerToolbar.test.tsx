/**
 * Composer toolbar (seam 1: the `Composer`) — the send payload pinned before
 * the Phase 4 rebuild replaces the Composer's chrome (ticket 26): Enter, the
 * GIF and tags. Every check asserts at `onSend`; for the same inputs it must
 * receive the same `SendArgs` after the rebuild (spec, Contracts). A later
 * ticket may change how a test reaches a control, but not what it asserts.
 *
 * Ticket 27 adds the two rows: "Composer buttons" and "Composer toolbar",
 * their order, the blocked chat and Send's enabled state.
 *
 * Ticket 28 turns the parked Lines and ⌘ triggers into the "AI" and
 * "Scripts" pills, and pins what a pick from each puts in the Composer.
 * The "AI" pill is now the AI Copilot; its picks are pinned in
 * `CopilotPicker.test.tsx`.
 *
 * Ticket 29 ends the button row with the "+" Extras overflow, holding free
 * previews, the "at" presets and the quick emojis. TODO.md A2 drops "+":
 * free previews show inline in the PPV row, the presets sit under ⏱ and
 * the quick emojis are a row after ⚙ that ⚙'s Save fills (A1).
 *
 * Ticket 30 puts the "PPV" pill in the price control's slot; the price moves
 * into the PPV row (`PpvRow.test.tsx`).
 *
 * Ticket 31 puts ⏱ "Timed message" after "PPV" (`TimedMessagePopover.test.tsx`)
 * and removes the ▾ quick-send split from Send.
 *
 * Ticket 33 puts ⚙ "Emoji favourites" after the emoji picker: up to 40
 * favourites, which the emoji picker shows first.
 *
 * Ticket 34 adds Upload (opens the Vault picker, as Vault does), @ "Mention"
 * (inserts the Fan's @username) and "Aa" (Not wired) to the bottom toolbar.
 * TODO.md A5 drops "Mention": the @ icon is "Tag other Creators" now.
 * On 2026-10-16 Upload opens the computer's file chooser instead (the
 * upload chips are pinned in `ComposerUpload.test.tsx`).
 *
 * Ticket 35 makes GIF and "Tag other Creators" 34px icons; the tag popover
 * stages picks until "Add", and its "More" › "Add a tag" › "Release form" is
 * Not wired.
 *
 * Ticket 36 puts "Translate" between "Aa" and Send: its popover's "Use
 * translation" switch drives the same translate mode as the Chat header's 🌐.
 *
 * Look-and-feel ticket 147 (docs/spec/messages-pro-look-and-feel/
 * phase-05-composer.md, Gap rows C1–C8, C13) makes the Composer Infloww's
 * three rows: "Composer buttons" holds no input, the textbox is a row of its
 * own before "Composer toolbar", the pills' labels fold to screen-reader text
 * below the row-1 threshold, and ⚙'s panel opens from its left edge.
 *
 * Look-and-feel ticket 148 (Gap rows C10, C11) opens the PPV row between the
 * textbox and "Composer toolbar", under the reply strip.
 *
 * Look-and-feel ticket 150 (user stories 4–7) gives the textbox Infloww's
 * placeholder and makes it true: a draft that is "/" + a keyword lists the
 * matching Scripts, and Enter loads the first one as a "Scripts" pick would.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import {
  expectDomOrder, pickSendAt, renderComposer, resetComposerHarness, routeRelay,
} from "./composerTestHarness";
import { readTranslateMode, useTranslateMode } from "@/hooks/useTranslateMode";
import { MP } from "@/lib/messagesPro";
import { NOT_WIRED } from "./NotWired";

beforeEach(() => resetComposerHarness());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;

describe("Composer toolbar: the three rows", () => {
  it('"Composer buttons" holds emoji, ⚙, the quick emojis, AI, Scripts, PPV and ⏱ in order and no textbox; "Composer toolbar" holds its controls in order', async () => {
    await renderComposer();

    const row1 = screen.getByRole("toolbar", { name: "Composer buttons" });
    const buttons = within(row1);
    const quick = within(buttons.getByRole("group", { name: "Quick emojis" })).getAllByRole("button");
    const row1Buttons = [
      buttons.getByRole("button", { name: "Emoji picker" }),
      buttons.getByRole("button", { name: "Emoji favourites" }), // ticket 33
      ...quick, // TODO.md A2
      buttons.getByRole("button", { name: "AI" }),
      buttons.getByRole("button", { name: "Scripts" }),
      buttons.getByRole("button", { name: "PPV" }), // ticket 30: the pill replaces the price slot
      buttons.getByRole("button", { name: "Timed message" }), // ticket 31
    ];
    expect(quick).toHaveLength(8);
    expectDomOrder(row1Buttons);
    // Ticket 147 (C2): row 1 holds exactly these and no input; A2 drops "+".
    expect(buttons.getAllByRole("button")).toEqual(row1Buttons);
    expect(buttons.queryByRole("textbox")).not.toBeInTheDocument();

    const toolbar = within(screen.getByRole("toolbar", { name: "Composer toolbar" }));
    const toolbarButtons = [
      toolbar.getByRole("button", { name: "Upload" }), // ticket 34
      toolbar.getByRole("button", { name: "GIF" }), // ticket 35
      toolbar.getByRole("button", { name: "Vault" }),
      toolbar.getByRole("button", { name: "Schedule" }),
      toolbar.getByRole("button", { name: "Tag other Creators" }), // ticket 35; the @ since A5
      toolbar.getByRole("button", { name: "Aa" }), // ticket 34
      toolbar.getByRole("button", { name: "Translate" }), // ticket 36
      toolbar.getByRole("button", { name: "Send" }),
    ];
    expectDomOrder(toolbarButtons);
    // Ticket 31: Send has no ▾ menu. Ticket 36: the row holds exactly these; A5 drops "Mention".
    expect(toolbar.getAllByRole("button")).toEqual(toolbarButtons);
    expect(toolbar.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it('the textbox is row 2: after "Composer buttons" and before "Composer toolbar"', async () => {
    await renderComposer();

    const row1 = screen.getByRole("toolbar", { name: "Composer buttons" });
    const row3 = screen.getByRole("toolbar", { name: "Composer toolbar" });
    // A node inside a row also "follows" it, so containment is checked first.
    expect(row1.contains(textbox()) || row3.contains(textbox())).toBe(false);
    expectDomOrder([row1, textbox(), row3]);
  });

  it('the PPV row opens between row 2 and row 3: after the textbox and the reply strip, before "Composer toolbar"; the notices stay above row 1 (C10)', async () => {
    const user = userEvent.setup();
    await renderComposer({
      quoted: { messageId: 1, preview: "Synthetic quote", authorName: "fan" },
      canSend: false, cannotSendReason: "Fan unsubscribed",
    });

    await user.click(screen.getByRole("button", { name: "PPV" }));
    const row1 = screen.getByRole("toolbar", { name: "Composer buttons" });
    const row3 = screen.getByRole("toolbar", { name: "Composer toolbar" });
    const ppvRow = screen.getByRole("group", { name: "PPV row" });
    const replyStrip = screen.getByText(/Replying to: Synthetic quote/);
    for (const el of [ppvRow, replyStrip]) {
      expect(row1.contains(el) || row3.contains(el) || el.contains(textbox())).toBe(false);
    }
    expectDomOrder([screen.getByText(/Fan unsubscribed/), row1, textbox(), replyStrip, ppvRow, row3]);
    // The PPV row is a row of the Composer, beside rows 1 and 3, with its
    // own 16px side inset (C11) and no wrapper adding a second one.
    expect(ppvRow.parentElement).toBe(row3.parentElement);
    expect(ppvRow.className.split(/\s+/)).toEqual(expect.arrayContaining(["px-4", "gap-2"]));
  });

  it("AI, Scripts and PPV keep their names, and each label is screen-reader text only below a 480px Thread", async () => {
    await renderComposer({ fanId: 501 });

    const row1 = within(screen.getByRole("toolbar", { name: "Composer buttons" }));
    for (const name of ["AI", "Scripts", "PPV"]) {
      const pill = row1.getByRole("button", { name });
      // C5 and the row-1 label threshold (spec ASSUMPTION: 480px).
      const label = within(pill).getByText(name);
      expect(label).not.toBe(pill);
      expect(label.className.split(/\s+/)).toEqual(expect.arrayContaining(["sr-only", "@min-[480px]:not-sr-only"]));
    }
    expect(row1.getByRole("button", { name: "PPV" })).toHaveAttribute("aria-pressed", "false");
  });

  it("below md GIF stays hidden in row 3; the @ tag button shows at every width", async () => {
    await renderComposer();

    const wrapper = screen.getByRole("button", { name: "GIF" }).closest(".hidden");
    expect(wrapper?.className.split(/\s+/)).toEqual(expect.arrayContaining(["hidden", "md:contents"]));
    expect(screen.getByRole("button", { name: "Tag other Creators" }).closest(".hidden")).toBeNull();
  });

  it("a blocked chat shows the reason and Send is disabled", async () => {
    const user = userEvent.setup();
    await renderComposer({ canSend: false, cannotSendReason: "Fan unsubscribed" });

    expect(screen.getByText(/Fan unsubscribed/)).toBeInTheDocument();
    await user.type(textbox(), "hi");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("Send is disabled for an empty draft, enabled after typing, and its title is the keyboard hint", async () => {
    const user = userEvent.setup();
    await renderComposer();

    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    // Infloww's idle Send: a grey #666 fill and #979797 label (page-parity 07 CP11).
    expect(send).toHaveClass("bg-[var(--inf-send-idle,var(--color-bg-elev-2))]", "text-[var(--inf-send-idle-text,var(--color-fg-dim))]");
    await user.type(textbox(), "hi");
    expect(send).toBeEnabled();
    expect(send).not.toHaveClass("bg-[var(--inf-send-idle,var(--color-bg-elev-2))]");
    expect(send).toHaveAttribute("title", "Enter to send · Shift+Enter for newline");
    expect(screen.queryByText("Enter to send · Shift+Enter for newline")).not.toBeInTheDocument();
  });
});

describe("Composer toolbar: Upload, @ and Aa", () => {
  it("Vault opens the Vault picker", async () => {
    const user = userEvent.setup();
    await renderComposer();

    expect(screen.queryByRole("dialog", { name: "Vault picker stub" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vault" }));
    expect(screen.getByRole("dialog", { name: "Vault picker stub" })).toBeInTheDocument();
  });

  // Disk upload restored 2026-10-16 (ComposerUpload.test.tsx covers the chips).
  it('Upload, titled "Upload from computer", opens the file chooser and not the Vault picker', async () => {
    const user = userEvent.setup();
    await renderComposer();
    const click = vi.spyOn(HTMLInputElement.prototype, "click");

    const upload = screen.getByRole("button", { name: "Upload" });
    expect(upload).toHaveAttribute("title", "Upload from computer");
    await user.click(upload);

    const input = screen.getByLabelText("Upload from computer");
    expect(input).toHaveAttribute("type", "file");
    expect(input).toHaveAttribute("multiple");
    expect(input).toHaveAttribute("accept", "image/*,video/*");
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.contexts[0]).toBe(input);
    expect(screen.queryByRole("dialog", { name: "Vault picker stub" })).not.toBeInTheDocument();
    click.mockRestore();
  });

  it('the @ icon is "Tag other Creators", there is no separate tag icon and no "Mention this fan" (TODO.md A5)', async () => {
    await renderComposer();

    const toolbar = screen.getByRole("toolbar", { name: "Composer toolbar" });
    const tag = within(toolbar).getByRole("button", { name: "Tag other Creators" });
    expect(tag.querySelector("svg.lucide-at-sign")).not.toBeNull();
    expect(toolbar.querySelector("svg.lucide-tag")).toBeNull();
    expect(screen.queryByRole("button", { name: "Mention" })).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Mention this fan/)).not.toBeInTheDocument();
  });

  it('"Aa" is Not wired: aria-disabled, titled with its excuse, and a click shows it and changes nothing', async () => {
    const user = userEvent.setup();
    await renderComposer();

    const aa = screen.getByRole("button", { name: "Aa" });
    expect(aa).toHaveAttribute("aria-disabled", "true");
    expect(aa).toHaveAttribute("title", `not wired: ${NOT_WIRED.aa}`);
    // Drawn at full strength in Infloww's glyph grey, not faded (page-parity 07 CP12).
    expect(aa).toHaveClass("text-[var(--inf-composer-glyph,var(--color-fg-dim))]");
    await user.click(aa);
    expect(screen.getByRole("status")).toHaveTextContent(NOT_WIRED.aa);
  });

  it("the AI pill is Infloww's teal-grey with a bot glyph, the Scripts pill its grey, and emoji a line smiley (page-parity 07 CP9, CP10)", async () => {
    await renderComposer();

    const row1 = within(screen.getByRole("toolbar", { name: "Composer buttons" }));
    const ai = row1.getByRole("button", { name: "AI" });
    expect(ai).toHaveClass("bg-[var(--inf-ai-pill,var(--color-bg-elev-2))]");
    expect(ai.querySelector("svg")).toHaveClass("lucide-bot");
    expect(row1.getByRole("button", { name: "Scripts" })).toHaveClass("bg-[var(--inf-scripts-pill,var(--color-bg-elev-2))]");
    expect(row1.getByRole("button", { name: "Emoji picker" }).querySelector("svg")).toHaveClass("lucide-smile");
  });
});

describe("Composer toolbar: Translate", () => {
  it('"Use translation" flips aria-checked and the translate mode the Chat header shares', async () => {
    const user = userEvent.setup();
    await renderComposer();

    const translate = screen.getByRole("button", { name: "Translate" });
    expect(translate).toHaveAttribute("aria-expanded", "false");
    await user.click(translate);
    expect(translate).toHaveAttribute("aria-expanded", "true");
    const popover = within(screen.getByRole("region", { name: "Translate" }));
    expect(popover.getByText("Translate messages from fans into")).toBeInTheDocument();
    expect(popover.getByText("English")).toBeInTheDocument();

    const useTranslation = popover.getByRole("switch", { name: "Use translation" });
    expect(useTranslation).toHaveAttribute("aria-checked", "false");
    await user.click(useTranslation);
    expect(useTranslation).toHaveAttribute("aria-checked", "true");
    expect(readTranslateMode()).toBe(true);

    // The 🌐 toggle flips the mode through the same hook; the switch follows.
    const header = renderHook(() => useTranslateMode());
    act(() => header.result.current[1](false));
    expect(useTranslation).toHaveAttribute("aria-checked", "false");
    expect(readTranslateMode()).toBe(false);
  });
});

describe("Composer toolbar: keyboard", () => {
  it("Enter sends", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(textbox(), "hi{Enter}");

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "hi" });
  });

  it("Shift+Enter inserts a newline and does not send", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(textbox(), "a{Shift>}{Enter}{/Shift}b");

    expect(textbox().value).toBe("a\nb");
    expect(onSend).not.toHaveBeenCalled();
  });
});

describe("Composer toolbar: GIF and tags", () => {
  it("one picked GIF sends its GIF id", async () => {
    routeRelay("/giphy/proxy/gifs/trending", () => ({
      data: [{
        type: "gif", id: "gif-synthetic-1", title: "Synthetic wave",
        images: { original: { url: "https://gif.test/1.gif" } },
      }],
      pagination: { total_count: 1, offset: 0 },
    }));
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.click(screen.getByRole("button", { name: "GIF" }));
    await user.click(await screen.findByRole("button", { name: "Synthetic wave" }));
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "", giphyId: "gif-synthetic-1" });
  });

  /** Open "Tag other Creators" and pick the synthetic Creator; returns the popover. */
  async function pickCreator(user: ReturnType<typeof userEvent.setup>) {
    routeRelay("/posts/tagged-friend-users", () => ({
      items: [{ id: 7001, user: { id: 7001, name: "Creator Synthetic", username: "creator_synth" } }],
      hasMore: false,
    }));
    await user.click(screen.getByRole("button", { name: "Tag other Creators" }));
    const popover = within(screen.getByRole("region", { name: "Tag other Creators" }));
    await user.click(await popover.findByRole("button", { name: /Creator Synthetic/ }));
    return popover;
  }

  it("one tagged Creator sends taggedUsers", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    const popover = await pickCreator(user);
    await user.click(popover.getByRole("button", { name: "Add" })); // ticket 35
    await user.type(textbox(), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "hi", taggedUsers: [7001] });
  });

  it('"Tag other Creators" stages picks until "Add", which shows the chip and closes the popover', async () => {
    const user = userEvent.setup();
    await renderComposer();

    const popover = await pickCreator(user);
    expect(popover.getByText("Tag other Creators")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Creator Synthetic" })).not.toBeInTheDocument();

    await user.click(popover.getByRole("button", { name: "Add" }));

    expect(screen.getByRole("button", { name: "Remove Creator Synthetic" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Tag other Creators" })).not.toBeInTheDocument();
  });

  it('a pick without "Add" is not sent', async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await pickCreator(user);
    await user.type(textbox(), "hi"); // a pointerdown outside closes the popover unapplied
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "hi" });
  });

  it('"More" › "Add a tag" › "Release form" is disabled, titled "not wired: <excuse>"', async () => {
    const user = userEvent.setup();
    await renderComposer();

    await user.click(screen.getByRole("button", { name: "Tag other Creators" }));
    const popover = within(screen.getByRole("region", { name: "Tag other Creators" }));
    expect(popover.queryByRole("button", { name: "Release form" })).not.toBeInTheDocument();
    await user.click(popover.getByRole("button", { name: "More" }));

    const addTag = within(popover.getByRole("group", { name: "Add a tag" }));
    const releaseForm = addTag.getByRole("button", { name: "Release form" });
    expect(releaseForm).toBeDisabled();
    expect(releaseForm).toHaveAttribute("title", `not wired: ${NOT_WIRED.releaseForm}`);
  });
});

describe('Composer toolbar: "Scripts"', () => {
  it('"Scripts": step 1 of a two-step Script loads text, price and media, and after Send step 2 is suggested', async () => {
    const step = (n: number, text: string) => ({
      id: 8800 + n, account_id: "acct-1", title: `Synthetic step ${n}`, text,
      price: 15, locked_text: false, media: [{ id: 9200 + n, type: "photo" }],
      script_id: "synthetic-script", script_step: n,
    });
    routeRelay("/admin/saved-replies", () => ({
      list: [step(1, "Synthetic opener"), step(2, "Synthetic follow-up")],
    }));
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 501 });

    await user.click(screen.getByRole("button", { name: "Scripts" }));
    await user.click(await screen.findByRole("button", { name: /Synthetic opener/ }));

    expect(textbox().value).toBe("Synthetic opener");
    for (const input of screen.getAllByRole("textbox", { name: "PPV price" })) {
      expect((input as HTMLInputElement).value).toBe("15");
    }
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({
      text: "Synthetic opener", price: 15, lockedText: false,
      attached: [{ id: 9201, type: "photo", files: null }],
    });
    expect(await screen.findByText(/Next in “synthetic-script” · step 2/)).toBeInTheDocument();
  });

  it("two templates at the next step show one chip each, by title; tapping one loads that one (4.16)", async () => {
    const reply = (id: number, step: number, title: string, text: string) => ({
      id, account_id: "acct-1", title, text, price: 0, locked_text: false, media: [],
      script_id: "synthetic-script", script_step: step,
    });
    routeRelay("/admin/saved-replies", () => ({
      list: [
        reply(8811, 1, "Synthetic opener", "Synthetic opener"),
        reply(8812, 2, "Bought", "Synthetic thanks"),
        reply(8813, 2, "Not bought", "Synthetic nudge"),
      ],
    }));
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 501 });

    await user.click(screen.getByRole("button", { name: "Scripts" }));
    await user.click(await screen.findByRole("button", { name: /Synthetic opener/ }));
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));

    expect(await screen.findAllByText(/Next in “synthetic-script” · step 2/)).toHaveLength(2);
    expect(screen.getByText("Bought:")).toBeInTheDocument();
    await user.click(screen.getByText("Not bought:"));
    expect(textbox().value).toBe("Synthetic nudge");
  });
});

describe('Composer toolbar: "/" + keyword searches Scripts', () => {
  const step = (n: number, text: string) => ({
    id: 8800 + n, account_id: "acct-1", title: `Synthetic step ${n}`, text,
    price: 15, locked_text: false, media: [{ id: 9200 + n, type: "photo" }],
    script_id: "synthetic-script", script_step: n,
  });
  const routeScripts = () => routeRelay("/admin/saved-replies", () => ({
    list: [step(1, "Synthetic opener"), step(2, "Synthetic follow-up")],
  }));
  /** What a pick of step 1 then Send puts on the wire (the "Scripts" test above). */
  const STEP_1_SEND = {
    text: "Synthetic opener", price: 15, lockedText: false,
    attached: [{ id: 9201, type: "photo", files: null }],
  };

  it('"/opener" lists only the matching Script with focus kept in the textbox; Enter loads its text, price and media without a send, and Send then carries what a "Scripts" pick and Send carry', async () => {
    routeScripts();
    const user = userEvent.setup();
    const pill = await renderComposer({ fanId: 501 });
    await user.click(screen.getByRole("button", { name: "Scripts" }));
    await user.click(await screen.findByRole("button", { name: /Synthetic opener/ }));
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(pill.onSend).toHaveBeenCalledTimes(1));
    const pillArgs = pill.onSend.mock.calls[0][0];
    expect(pillArgs).toEqual(STEP_1_SEND);
    cleanup();
    resetComposerHarness();

    routeScripts();
    const { onSend } = await renderComposer({ fanId: 501 });
    await user.type(textbox(), "/opener");

    expect(await screen.findByRole("button", { name: /Synthetic opener/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Synthetic follow-up/ })).not.toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 60)); // past the panel's own focus timer
    expect(textbox()).toHaveFocus();

    await user.keyboard("{Enter}");

    expect(textbox().value).toBe("Synthetic opener");
    for (const input of screen.getAllByRole("textbox", { name: "PPV price" })) {
      expect((input as HTMLInputElement).value).toBe("15");
    }
    expect(screen.queryByRole("button", { name: /Synthetic opener/ })).not.toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend.mock.calls[0][0]).toEqual(pillArgs);
  });

  it('"/" alone lists every Script', async () => {
    routeScripts();
    const user = userEvent.setup();
    await renderComposer({ fanId: 501 });

    await user.type(textbox(), "/");

    expect(await screen.findByRole("button", { name: /Synthetic opener/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Synthetic follow-up/ })).toBeInTheDocument();
  });

  it("Escape closes the list until the draft changes, and closes only the list", async () => {
    routeScripts();
    const user = userEvent.setup();
    await renderComposer({ fanId: 501 });
    await user.type(textbox(), "/synth");
    await screen.findByRole("button", { name: /Synthetic opener/ });
    // Find and the overlay Fan insights hear Escape on `window`.
    const windowEscape = vi.fn((e: KeyboardEvent) => { if (e.key === "Escape") return e.key; });
    window.addEventListener("keydown", windowEscape);

    await user.keyboard("{Escape}");

    window.removeEventListener("keydown", windowEscape);
    expect(windowEscape).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Synthetic opener/ })).not.toBeInTheDocument();
    expect(textbox().value).toBe("/synth");

    await user.type(textbox(), "e");

    expect(await screen.findByRole("button", { name: /Synthetic opener/ })).toBeInTheDocument();
  });

  it('Enter with no match sends nothing; Send still sends the "/word" draft as typed', async () => {
    routeScripts();
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 501 });
    await user.type(textbox(), "/nomatch");
    expect(await screen.findByText(/No templates match/)).toBeInTheDocument();

    await user.keyboard("{Enter}");

    expect(textbox().value).toBe("/nomatch");
    expect(onSend).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "/nomatch" });
  });

  it('with "/opener" as the draft, Enter on a focused Send sends "/opener" as typed and loads no Script', async () => {
    routeScripts();
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 501 });
    await user.type(textbox(), "/opener");
    await screen.findByRole("button", { name: /Synthetic opener/ });

    screen.getByRole("button", { name: "Send" }).focus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "/opener" });
    expect(textbox().value).not.toBe("Synthetic opener");
    expect(screen.queryByRole("textbox", { name: "PPV price" })).not.toBeInTheDocument();
  });

  it('a draft not starting with "/" opens no list and sends on Enter; Shift+Enter still adds a newline', async () => {
    routeScripts();
    const user = userEvent.setup();
    const { onSend } = await renderComposer({ fanId: 501 });

    await user.type(textbox(), "/opener{Shift>}{Enter}{/Shift}x");
    expect(textbox().value).toBe("/opener\nx");
    expect(screen.queryByRole("button", { name: /Synthetic opener/ })).not.toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();

    await user.clear(textbox());
    await user.type(textbox(), "see /opener{Enter}");

    expect(screen.queryByRole("button", { name: /Synthetic opener/ })).not.toBeInTheDocument();
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith({ text: "see /opener" });
  });
});

describe("Composer toolbar: what the \"+\" Extras overflow held (TODO.md A2, A3)", () => {
  it('there is no "+" overflow', async () => {
    await renderComposer();

    expect(screen.queryByRole("button", { name: "Inflowwww extras" })).not.toBeInTheDocument();
  });

  it("attaching media opens the PPV row with its price and shows free previews inline, enabled only with a price > 0", async () => {
    const user = userEvent.setup();
    await renderComposer();
    const ppvRow = () => screen.queryByRole("group", { name: "PPV row" });

    expect(ppvRow()).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vault" }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));

    // A3: attaching opens the price without a click on "PPV".
    const row = within(ppvRow()!);
    expect(screen.getByRole("button", { name: "PPV" })).toHaveAttribute("aria-pressed", "true");
    const price = row.getByRole("textbox", { name: "PPV price" });
    const previews = within(row.getByRole("group", { name: "Free previews" }));
    expect(previews.getByText("0/2")).toBeInTheDocument();
    expect(previews.getByRole("button", { name: "More free previews" })).toBeEnabled();

    await user.clear(price);
    expect(previews.getByRole("button", { name: "More free previews" })).toBeDisabled();
    await user.type(price, "5");
    await user.click(previews.getByRole("button", { name: "More free previews" }));
    expect(previews.getByText("1/2")).toBeInTheDocument();
  });

  it("without media there is no free previews stepper", async () => {
    const user = userEvent.setup();
    await renderComposer();

    await user.click(screen.getByRole("button", { name: "PPV" }));
    await user.type(screen.getByRole("textbox", { name: "PPV price" }), "5");
    expect(screen.queryByRole("group", { name: "Free previews" })).not.toBeInTheDocument();
  });

  it("price 0 on attached media sends it for free (A3)", async () => {
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.click(screen.getByRole("button", { name: "Vault" }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
    const price = screen.getByRole("textbox", { name: "PPV price" });
    await user.clear(price);
    await user.type(price, "0");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend.mock.calls[0][0].price).toBeUndefined();
    expect(onSend.mock.calls[0][0].attached).toHaveLength(2);
  });

  it('⏱ "+15m" turns schedule mode on and sets "at" to now plus 15 minutes without sending', async () => {
    // Only Date is faked: the clock is frozen, user-event's timers stay real.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-13T10:00:00.000Z"));
    const user = userEvent.setup();
    const { onSend } = await renderComposer();

    await user.type(textbox(), "hi");
    await pickSendAt(user, 15);

    expect(screen.queryByRole("region", { name: "Timed message" })).not.toBeInTheDocument();
    const at = screen.getByLabelText("Send at") as HTMLInputElement;
    expect(new Date(at.value).toISOString()).toBe("2026-10-13T10:15:00.000Z");
    expect(screen.getByRole("button", {
      name: "Schedule", description: "Enter to send · Shift+Enter for newline",
    })).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("a quick emoji inserts itself into the draft", async () => {
    const user = userEvent.setup();
    await renderComposer();

    await user.type(textbox(), "hi");
    const quick = within(screen.getByRole("group", { name: "Quick emojis" })).getAllByRole("button");
    await user.click(quick[0]);

    expect(textbox().value).toBe(`hi${quick[0].textContent}`);
  });
});

describe("Composer toolbar: popover placement", () => {
  const classes = (el: HTMLElement) => el.className.split(/\s+/);

  it("⚙'s panel carries popStart's classes: its left edge on ⚙'s, 8px above (C13)", async () => {
    const user = userEvent.setup();
    await renderComposer();

    await user.click(screen.getByRole("button", { name: "Emoji favourites" }));
    const panel = classes(screen.getByRole("region", { name: "Emoji favourites" }));
    expect(MP.ours.ComposerToolbar.popStart.split(" ")).toEqual(["left-0", "mb-2"]);
    expect(panel).toEqual(expect.arrayContaining(MP.ours.ComposerToolbar.popStart.split(" ")));
    expect(panel).not.toContain("right-0");
  });

  it("⏱ and Translate keep the shared pop: their right edge on the trigger's, 8px above", async () => {
    const user = userEvent.setup();
    await renderComposer();

    for (const name of ["Timed message", "Translate"]) {
      await user.click(screen.getByRole("button", { name }));
      const panel = classes(screen.getByRole("region", { name }));
      expect(panel).toEqual(expect.arrayContaining(["right-0", "mb-2"]));
      expect(panel).not.toContain("left-0");
      await user.click(screen.getByRole("button", { name }));
    }
  });
});

describe("Composer toolbar: emoji favourites", () => {
  it("⚙ starts from the quick emojis; Save makes the picks the quick emoji row, which persists (TODO.md A1)", async () => {
    const user = userEvent.setup();
    await renderComposer();
    const quickRow = () =>
      within(screen.getByRole("group", { name: "Quick emojis" })).getAllByRole("button").map((b) => b.textContent);
    const defaults = quickRow();
    expect(defaults).toHaveLength(8);

    await user.click(screen.getByRole("button", { name: "Emoji favourites" }));
    const editor = within(screen.getByRole("region", { name: "Emoji favourites" }));
    expect(editor.getByText("8/40")).toBeInTheDocument();
    const toggles = within(editor.getByRole("group", { name: "Emojis" })).getAllByRole("button");
    const extra = toggles.find((t) => !defaults.includes(t.textContent))!;
    await user.click(extra);
    await user.click(editor.getByRole("button", { name: "Save" }));

    const saved = [...defaults, extra.textContent];
    expect(quickRow()).toEqual(saved);
    expect(JSON.parse(localStorage.getItem("chatterly:emoji_favourites") ?? "null")).toEqual(saved);

    // A fresh Composer (a reload) reads them back.
    cleanup();
    await renderComposer();
    await waitFor(() => expect(quickRow()).toEqual(saved));
    await user.click(within(screen.getByRole("group", { name: "Quick emojis" })).getAllByRole("button")[8]);
    expect(textbox().value).toBe(extra.textContent);
  });

  describe("from an empty saved list", () => {
    beforeEach(() => localStorage.setItem("chatterly:emoji_favourites", "[]"));

    /** Open ⚙ and toggle the first 40 emojis of its grid, last to first, so
     *  pick order is not grid order; returns the editor, its toggles and the
     *  40 picked, in pick order. */
    async function pickForty(user: ReturnType<typeof userEvent.setup>) {
      await user.click(screen.getByRole("button", { name: "Emoji favourites" }));
      const editor = within(screen.getByRole("region", { name: "Emoji favourites" }));
      const toggles = within(editor.getByRole("group", { name: "Emojis" })).getAllByRole("button");
      const order = toggles.slice(0, 40).reverse();
      for (const toggle of order) await user.click(toggle);
      return { editor, toggles, picked: order.map((t) => t.textContent) };
    }

    it("at 40/40 the 41st toggle is disabled, and removing one frees it", async () => {
      const user = userEvent.setup();
      await renderComposer();

      const { editor, toggles } = await pickForty(user);

      expect(editor.getByText("40/40")).toBeInTheDocument();
      expect(toggles[40]).toBeDisabled();
      expect(toggles[0]).toHaveAttribute("aria-pressed", "true");
      await user.click(toggles[0]);
      expect(editor.getByText("39/40")).toBeInTheDocument();
      expect(toggles[40]).toBeEnabled();
    });

    it('"Save" writes the 40 favourites in pick order and closes the editor; "Cancel" discards', async () => {
      const user = userEvent.setup();
      await renderComposer();

      const { editor, picked } = await pickForty(user);
      await user.click(editor.getByRole("button", { name: "Save" }));

      expect(JSON.parse(localStorage.getItem("chatterly:emoji_favourites") ?? "null")).toEqual(picked);
      expect(screen.queryByRole("region", { name: "Emoji favourites" })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Emoji favourites" }));
      const reopened = within(screen.getByRole("region", { name: "Emoji favourites" }));
      expect(reopened.getByText("40/40")).toBeInTheDocument();
      await user.click(within(reopened.getByRole("group", { name: "Emojis" })).getAllByRole("button")[0]);
      await user.click(reopened.getByRole("button", { name: "Cancel" }));
      expect(JSON.parse(localStorage.getItem("chatterly:emoji_favourites") ?? "null")).toHaveLength(40);
    });

    it('reopening the emoji picker shows "Favourites" first', async () => {
      const user = userEvent.setup();
      await renderComposer();
      const picker = screen.getByRole("button", { name: "Emoji picker" });

      await user.click(picker);
      expect(screen.queryByRole("button", { name: "Favourites" })).not.toBeInTheDocument();
      await user.click(picker);

      const { editor, picked } = await pickForty(user);
      await user.click(editor.getByRole("button", { name: "Save" }));
      await user.click(picker);

      const favourites = screen.getByRole("button", { name: "Favourites" });
      expect(favourites).toHaveAttribute("aria-pressed", "true");
      expectDomOrder([favourites, screen.getByTitle("flirty")]);
      // The grid under the tab strip shows the favourites, in pick order.
      const grid = favourites.parentElement!.nextElementSibling as HTMLElement;
      expect(within(grid).getAllByRole("button").map((b) => b.textContent)).toEqual(picked);
    });
  });
});
