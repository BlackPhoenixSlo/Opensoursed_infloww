/**
 * MessagingSettingsTab — the Messaging settings Panel (docs/spec/settings-tabs/phase-04-time-tracking-messaging.md).
 *
 * Rendered with the relay mocked at `fetch` by URL: the stub serves the `messaging` Settings blob,
 * so every save assertion is an assertion about the wire.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import MessagingSettingsTab from "@/components/settings/MessagingSettingsTab";

type Call = { method: string; url: string; body: unknown };

const URL = "/admin/settings/messaging";
/** The stored blob: translation off with a prompt, so a PUT that drops or blanks the prompt cannot pass. */
const STORED = { ai_translation: false, prompt: "Alpha One house prompt" };
const SWITCH = "Enable AI translation in Messages Pro for employees in your organization";

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET answers. */
let getReply: () => Response | Promise<Response>;
/** What PUT answers, given the body it was sent. */
let putReply: (body: unknown) => Response | Promise<Response>;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const puts = () => calls().filter((c) => c.method === "PUT");
const settle = () => new Promise((r) => setTimeout(r, 20));

beforeEach(() => {
  getReply = () => jsonRes({ tab: "messaging", config: STORED });
  putReply = (body) => jsonRes({ tab: "messaging", config: body });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === URL && method === "GET") return getReply();
    if (url === URL && method === "PUT") return putReply(JSON.parse(String(init?.body)));
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const toggle = () => screen.getByRole("switch", { name: SWITCH });
const edit = () => screen.getByRole("button", { name: "Edit" });
const promptBox = () => screen.getByRole("textbox", { name: "AI Translator prompt" });
const button = (name: string) => screen.getByRole("button", { name });
/** A Card's box, found from its title span (Card: box > header row > title span). */
const card = (title: string) => screen.getByText(title, { selector: "span" }).parentElement!.parentElement as HTMLElement;

/** Edit, then replace the prompt with `text` in the open editor. */
function typePrompt(text: string) {
  fireEvent.click(edit());
  fireEvent.change(promptBox(), { target: { value: text } });
}

async function mountLoaded() {
  renderWithProviders(<MessagingSettingsTab />);
  await waitFor(() => expect(toggle()).toBeEnabled());
}

describe("MessagingSettingsTab", () => {
  it("shows the Panel, notes saying what translation uses and that the prompt is unused, and the AI translation card with the stored switch state", async () => {
    getReply = () => jsonRes({ tab: "messaging", config: { ...STORED, ai_translation: true } });
    await mountLoaded();
    expect(screen.getByRole("heading", { name: "Messaging settings" })).toBeInTheDocument();
    // Ticket 28 closed (LLM tier vetoed): no "not applied yet" note; each card says what actually happens.
    expect(screen.queryByText(/not applied yet/)).toBeNull();
    const switchCard = within(card("AI translation"));
    expect(switchCard.getByText(/translated to English when someone turns on “Use translation”/)).toBeInTheDocument();
    expect(switchCard.getByText(/Google's free translate service \(no API key needed\)/)).toBeInTheDocument();
    expect(switchCard.getByText(/can't turn on “Use translation”, don't see Translate on messages/)).toBeInTheDocument();
    // The note links the real pages the switch governs.
    expect(switchCard.getByRole("link", { name: "Messages Pro" })).toHaveAttribute("href", "/messages-pro");
    expect(switchCard.getByRole("link", { name: "employees" })).toHaveAttribute("href", "/employees");
    const promptCard = within(card("AI Translator prompt"));
    expect(promptCard.getByText(
      "Saved for your organization, but not used: Google's free translate service takes no instructions.",
    )).toBeInTheDocument();
    expect(switchCard.queryByText(/but not used/)).toBeNull();
    expect(screen.getByText("AI translation")).toBeInTheDocument();
    // The caption under the title row says what the switch does, in the switch's own words.
    expect(screen.getByText(SWITCH, { selector: "p" })).toBeInTheDocument();
    expect(toggle()).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("an empty stored blob shows the switch on (default), as the Relay's gate reads it", async () => {
    getReply = () => jsonRes({ tab: "messaging", config: {} });
    await mountLoaded();
    expect(toggle()).toHaveAttribute("aria-checked", "true");
  });

  it("the switch and the prompt's Edit are disabled before the blob loads", async () => {
    let answer!: (r: Response) => void;
    getReply = () => new Promise<Response>((r) => (answer = r));
    renderWithProviders(<MessagingSettingsTab />);
    await waitFor(() => expect(calls()).toHaveLength(1));
    expect(toggle()).toBeDisabled();
    expect(edit()).toBeDisabled();
    fireEvent.click(toggle());
    await settle();
    expect(puts()).toEqual([]);
    answer(jsonRes({ tab: "messaging", config: STORED }));
    await waitFor(() => expect(toggle()).toBeEnabled());
  });

  it("flipping the switch PUTs the whole blob at once, carrying the stored prompt, and shows it on", async () => {
    await mountLoaded();
    fireEvent.click(toggle());
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()).toEqual([{ method: "PUT", url: URL, body: { ai_translation: true, prompt: "Alpha One house prompt" } }]);
    await waitFor(() => expect(toggle()).toBeEnabled());
    expect(toggle()).toHaveAttribute("aria-checked", "true");
  });

  it("the switch is disabled while its save runs, so a second flip sends nothing", async () => {
    let answer!: (r: Response) => void;
    putReply = () => new Promise<Response>((r) => (answer = r));
    await mountLoaded();
    fireEvent.click(toggle());
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(toggle()).toBeDisabled();
    fireEvent.click(toggle());
    await settle();
    expect(puts()).toHaveLength(1);
    answer(jsonRes({ tab: "messaging", config: { ai_translation: true, prompt: "Alpha One house prompt" } }));
    await waitFor(() => expect(toggle()).toBeEnabled());
    expect(toggle()).toHaveAttribute("aria-checked", "true");
  });

  it("a 500 on the switch PUT flips it back and shows the error, after exactly one PUT", async () => {
    putReply = () => jsonRes({ detail: "boom" }, 500);
    await mountLoaded();
    fireEvent.click(toggle());
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
    expect(toggle()).toHaveAttribute("aria-checked", "false");
    expect(toggle()).toBeEnabled();
    expect(puts()).toHaveLength(1);
  });

  it("a failed load keeps the switch disabled, says so beside Retry, and sends no PUT (Load gate)", async () => {
    getReply = () => jsonRes({ detail: "boom" }, 500);
    renderWithProviders(<MessagingSettingsTab />);
    await waitFor(() => expect(calls()).toHaveLength(1));
    await settle();
    expect(toggle()).toBeDisabled();
    expect(screen.getByText("These settings never loaded — saving would replace them with defaults.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    fireEvent.click(toggle());
    await settle();
    expect(puts()).toEqual([]);
  });

  it("the AI Translator prompt card shows the stored prompt in a read-only textarea with its n/2000 counter, and \"No prompt set\" for an empty one", async () => {
    await mountLoaded();
    expect(screen.getByText("AI Translator prompt")).toBeInTheDocument();
    expect(promptBox()).toHaveValue("Alpha One house prompt");
    expect(promptBox()).toHaveAttribute("readonly");
    expect(screen.getByText("22/2000")).toBeInTheDocument();
    expect(edit()).toBeEnabled();
    cleanup();
    getReply = () => jsonRes({ tab: "messaging", config: {} });
    await mountLoaded();
    expect(promptBox()).toHaveValue("");
    expect(promptBox()).toHaveAttribute("placeholder", "No prompt set");
    expect(screen.getByText("0/2000")).toBeInTheDocument();
  });

  it("Edit makes the stored prompt editable with Cancel and Save, and sends nothing", async () => {
    await mountLoaded();
    fireEvent.click(edit());
    expect(promptBox()).toHaveValue("Alpha One house prompt");
    expect(promptBox()).not.toHaveAttribute("readonly");
    expect(promptBox()).toHaveAttribute("maxlength", "2000");
    expect(button("Cancel")).toBeEnabled();
    expect(button("Save")).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    await settle();
    expect(puts()).toEqual([]);
  });

  it("Edit → \"synthetic prompt\" → Save PUTs the stored switch value with the typed prompt, then shows it read-only", async () => {
    // The switch is stored ON (not the default), so a PUT that sends the default cannot pass.
    getReply = () => jsonRes({ tab: "messaging", config: { ...STORED, ai_translation: true } });
    await mountLoaded();
    typePrompt("synthetic prompt");
    fireEvent.click(button("Save"));
    await waitFor(() => expect(promptBox()).toHaveAttribute("readonly"));
    expect(puts()).toEqual([{ method: "PUT", url: URL, body: { ai_translation: true, prompt: "synthetic prompt" } }]);
    expect(promptBox()).toHaveValue("synthetic prompt");
    expect(toggle()).toHaveAttribute("aria-checked", "true");
  });

  it("prompt Cancel restores the stored text, closes the editor and sends nothing", async () => {
    await mountLoaded();
    typePrompt("synthetic prompt");
    fireEvent.click(button("Cancel"));
    expect(promptBox()).toHaveAttribute("readonly");
    expect(promptBox()).toHaveValue("Alpha One house prompt");
    fireEvent.click(edit());
    expect(promptBox()).toHaveValue("Alpha One house prompt");
    await settle();
    expect(puts()).toEqual([]);
  });

  it("with an unsaved prompt draft typed, a switch flip PUTs the stored prompt, not the draft, and keeps the draft", async () => {
    await mountLoaded();
    typePrompt("synthetic prompt");
    fireEvent.click(toggle());
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()).toEqual([{ method: "PUT", url: URL, body: { ai_translation: true, prompt: "Alpha One house prompt" } }]);
    await waitFor(() => expect(toggle()).toBeEnabled());
    expect(promptBox()).toHaveValue("synthetic prompt");
  });

  it("a 500 on the prompt PUT keeps the editor and its draft, shows the error by Save not under the switch, and a later flip sends the stored prompt", async () => {
    let n = 0;
    putReply = (body) => (++n === 1 ? jsonRes({ detail: "boom" }, 500) : jsonRes({ tab: "messaging", config: body }));
    await mountLoaded();
    typePrompt("synthetic prompt");
    fireEvent.click(button("Save"));
    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    expect(puts()).toEqual([{ method: "PUT", url: URL, body: { ai_translation: false, prompt: "synthetic prompt" } }]);
    expect(promptBox()).toHaveValue("synthetic prompt");
    expect(button("Save")).toBeEnabled();
    // The switch card's alert is the switch's own save's; the switch never moved.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(toggle()).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle());
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(puts()[1]).toEqual({ method: "PUT", url: URL, body: { ai_translation: true, prompt: "Alpha One house prompt" } });
    await waitFor(() => expect(toggle()).toBeEnabled());
    expect(screen.queryByText("boom")).toBeNull();
    expect(promptBox()).toHaveValue("synthetic prompt");
  });

  it("a failed prompt Save, then Cancel, then Edit, no longer shows the old error", async () => {
    putReply = () => jsonRes({ detail: "boom" }, 500);
    await mountLoaded();
    typePrompt("synthetic prompt");
    fireEvent.click(button("Save"));
    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    fireEvent.click(button("Cancel"));
    fireEvent.click(edit());
    expect(screen.queryByText("boom")).toBeNull();
  });

  it("a 500 on a switch flip with a draft open shows the error under the switch only, and keeps the draft", async () => {
    putReply = () => jsonRes({ detail: "boom" }, 500);
    await mountLoaded();
    typePrompt("synthetic prompt");
    fireEvent.click(toggle());
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
    expect(screen.getAllByText("boom")).toHaveLength(1);
    expect(promptBox()).toHaveValue("synthetic prompt");
  });

  it("no request reaches /admin/translate: every fetch call goes to the messaging blob", async () => {
    await mountLoaded();
    fireEvent.click(toggle());
    await waitFor(() => expect(puts()).toHaveLength(1));
    await settle();
    typePrompt("synthetic prompt");
    fireEvent.click(button("Save"));
    await waitFor(() => expect(puts()).toHaveLength(2));
    await settle();
    expect(calls().map((c) => `${c.method} ${c.url}`)).toEqual([`GET ${URL}`, `PUT ${URL}`, `PUT ${URL}`]);
  });
});
