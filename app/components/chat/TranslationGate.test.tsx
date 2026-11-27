import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

let session: "chatter" | "owner" = "chatter";
vi.mock("@/contexts/UserContext", async (orig) => ({
  ...(await orig<typeof import("@/contexts/UserContext")>()),
  useOptionalUser: () => ({ user: session === "owner" ? { username: "fixture-owner" } : null }),
}));
vi.mock("@/contexts/ChatterContext", async (orig) => ({
  ...(await orig<typeof import("@/contexts/ChatterContext")>()),
  useOptionalChatter: () => ({ chatter: { username: "fixture-chatter" } }),
}));

import { renderWithProviders } from "@/test-utils";
import { APPLIED_SETTINGS_KEY, type AppliedSettings } from "@/lib/appliedSettings";
import { readTranslateMode } from "@/hooks/useTranslateMode";
import { fanLanguageKey } from "@/lib/fanLanguage";
import { MessageList } from "@/components/chat/MessageList";
import {
  relayGet, relayPost, renderComposer, resetComposerHarness, routeRelay, tooltipOf,
} from "./composerTestHarness";
import { baseProps, bubbleBox, msg } from "./messageListTestHarness";

const STORAGE_KEY = "chatterly:translate-en";
const TURNED_OFF = "Turned off by your organization";

let aiTranslation = false;
const applied = (): AppliedSettings => ({
  preferences: { tz: null, report_tz: null, week_start: "monday" },
  messaging: { ai_translation: aiTranslation },
  permissions: { enforced: false, pages: null, scope: "all" },
  flags: { fansly_manager: false, leak_tracker: false },
});
let heldApplied: Promise<AppliedSettings> | null = null;

const translateCalls = () => relayPost.mock.calls.filter(([path]) => path === "/admin/translate");
const settle = () => act(() => new Promise((r) => setTimeout(r, 30)));

beforeEach(() => {
  resetComposerHarness();
  session = "chatter";
  aiTranslation = false;
  heldApplied = null;
  routeRelay("/admin/settings/applied", () => heldApplied ?? applied());
  localStorage.setItem(STORAGE_KEY, "1");
  window.dispatchEvent(new Event("storage"));
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  window.dispatchEvent(new Event("storage"));
});

async function openTranslate() {
  await userEvent.setup().click(screen.getByRole("button", { name: "Translate" }));
  return within(screen.getByRole("region", { name: "Translate" })).getByRole("switch", { name: "Use translation" });
}

describe("the Composer's \"Use translation\" switch", () => {
  it("is disabled with the tooltip while the Agency's AI translation is off, and a click leaves the stored mode as it was", async () => {
    const { queryClient } = await renderComposer();
    const useTranslation = await openTranslate();
    await waitFor(() => expect(useTranslation).toBeDisabled());
    expect(tooltipOf(useTranslation)).toBe(TURNED_OFF);
    expect(useTranslation).toHaveAttribute("aria-checked", "false");
    await userEvent.setup().click(useTranslation);
    expect(readTranslateMode()).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");
    expect(relayGet.mock.calls.find(([p]) => p === "/admin/settings/applied")?.[1]?.accountId).toBe("acct-1");

    aiTranslation = true;
    await act(() => queryClient.invalidateQueries({ queryKey: APPLIED_SETTINGS_KEY }));
    await waitFor(() => expect(useTranslation).toBeEnabled());
    expect(useTranslation).toHaveAttribute("aria-checked", "true");
    expect(tooltipOf(useTranslation)).not.toBe(TURNED_OFF);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");
  });

  it("offers no outbound translation while the Agency's AI translation is off: no strip for a Fan with a language, and \"Translate my messages\" disabled", async () => {
    localStorage.setItem(fanLanguageKey("acct-1", 200000001), "es");
    await renderComposer({ fanId: 200000001 });
    await openTranslate();
    const toggle = within(screen.getByRole("region", { name: "Translate" })).getByRole("button", { name: "Translate my messages" });
    await waitFor(() => expect(toggle).toBeDisabled());
    expect(tooltipOf(toggle)).toBe(TURNED_OFF);
    expect(screen.queryByRole("region", { name: "Translate my message" })).toBeNull();
  });

  it("is disabled until the chatter's Applied read answers, then follows the answer", async () => {
    let answer: (a: AppliedSettings) => void = () => {};
    heldApplied = new Promise<AppliedSettings>((r) => { answer = r; });
    await renderComposer();
    const useTranslation = await openTranslate();
    await settle();
    expect(useTranslation).toBeDisabled();
    expect(useTranslation).toHaveAttribute("aria-checked", "false");
    await userEvent.setup().click(useTranslation);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");

    aiTranslation = true;
    await act(async () => answer(applied()));
    await waitFor(() => expect(useTranslation).toBeEnabled());
    expect(useTranslation).toHaveAttribute("aria-checked", "true");
  });

  it("is never disabled for an owner session, whatever the Agency's switch says", async () => {
    session = "owner";
    await renderComposer();
    const useTranslation = await openTranslate();
    await settle();
    expect(useTranslation).toBeEnabled();
    expect(useTranslation).toHaveAttribute("aria-checked", "true");
    expect(tooltipOf(useTranslation)).not.toBe(TURNED_OFF);
  });
});

describe("the thread's translate requests", () => {
  const fanText = "gate check hola amiga";
  const thread = () => (
    <MessageList {...baseProps} ownerUserId={555} messages={[msg({ id: 501, text: fanText, fromUser: { id: 42 } })]} />
  );

  it("sends none while the Agency's AI translation is off and offers no per-bubble Translate; turned back on, the stored mode translates for the Creator in scope", async () => {
    relayPost.mockImplementation((path: string, body?: unknown) => Promise.resolve(path === "/admin/translate"
      ? { results: (body as { texts: string[] }).texts.map((t) => ({ text: `EN ${t}`, lang: "es" })) } : {}));
    const { container, queryClient } = renderWithProviders(thread());
    await waitFor(() => expect(relayGet.mock.calls.some(([p]) => p === "/admin/settings/applied")).toBe(true));
    await settle();
    expect(translateCalls()).toEqual([]);
    expect(within(container).queryByRole("button", { name: "Translate" })).toBeNull();
    expect(within(container).queryByRole("button", { name: "Show original" })).toBeNull();
    expect(bubbleBox(container, 501).textContent).toContain(fanText);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");

    aiTranslation = true;
    await act(() => queryClient.invalidateQueries({ queryKey: APPLIED_SETTINGS_KEY }));
    await waitFor(() => expect(bubbleBox(container, 501).textContent).toContain(`EN ${fanText}`));
    expect(translateCalls()).toEqual([["/admin/translate", { texts: [fanText], target: "en" }, { accountId: "acct1" }]]);
  });
});
