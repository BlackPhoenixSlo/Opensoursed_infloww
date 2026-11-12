/**
 * MessagingSettingsTab — the Messaging settings Panel: the AI translation switch only (docs/spec/settings-tabs/phase-04-time-tracking-messaging.md).
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
/** A Card's box, found from its title span (Card: box > header row > title span). */
const card = (title: string) => screen.getByText(title, { selector: "span" }).parentElement!.parentElement as HTMLElement;

async function mountLoaded() {
  renderWithProviders(<MessagingSettingsTab />);
  await waitFor(() => expect(toggle()).toBeEnabled());
}

describe("MessagingSettingsTab", () => {
  it("shows the Panel and one bordered AI translation card with a one-line help and the stored switch state; no prompt editor", async () => {
    getReply = () => jsonRes({ tab: "messaging", config: { ...STORED, ai_translation: true } });
    await mountLoaded();
    expect(screen.getByRole("heading", { name: "Messaging settings" })).toBeInTheDocument();
    expect(screen.queryByText(/not applied yet/)).toBeNull();
    const box = card("AI translation");
    expect(box.className).toContain("border");
    const switchCard = within(box);
    expect(switchCard.getByText(/^Lets employees translate chats in/)).toHaveTextContent(
      "Lets employees translate chats in Messages Pro. Owners always can.",
    );
    expect(switchCard.getByRole("link", { name: "Messages Pro" })).toHaveAttribute("href", "/messages-pro");
    expect(screen.queryByRole("textbox", { name: "AI Translator prompt" })).toBeNull();
    expect(screen.queryByText("AI Translator prompt")).toBeNull();
    expect(toggle()).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("an empty stored blob shows the switch on (default), as the Relay's gate reads it", async () => {
    getReply = () => jsonRes({ tab: "messaging", config: {} });
    await mountLoaded();
    expect(toggle()).toHaveAttribute("aria-checked", "true");
  });

  it("the switch is disabled before the blob loads", async () => {
    let answer!: (r: Response) => void;
    getReply = () => new Promise<Response>((r) => (answer = r));
    renderWithProviders(<MessagingSettingsTab />);
    await waitFor(() => expect(calls()).toHaveLength(1));
    expect(toggle()).toBeDisabled();
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

  it("no request reaches /admin/translate: every fetch call goes to the messaging blob", async () => {
    await mountLoaded();
    fireEvent.click(toggle());
    await waitFor(() => expect(puts()).toHaveLength(1));
    await settle();
    expect(calls().map((c) => `${c.method} ${c.url}`)).toEqual([`GET ${URL}`, `PUT ${URL}`]);
  });
});
