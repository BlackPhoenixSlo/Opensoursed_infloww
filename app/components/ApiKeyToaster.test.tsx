/**
 * ApiKeyToaster + AiKeyNotice — the one notification for a missing/empty/wrong
 * AI key. Pinned: the relay's message and the Settings › AI keys link for an
 * owner; the message without a link (and "ask your agency owner") for a
 * chatter; identical toasts inside the dedupe window are one; the dismiss
 * button; and the automation notice renders the relay's `notices`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

const chatterState: { chatter: unknown } = { chatter: null };
vi.mock("@/contexts/ChatterContext", () => ({
  useOptionalChatter: () => chatterState,
}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn() } };
});

import { ApiKeyToaster, DEDUPE_MS } from "@/components/ApiKeyToaster";
import { AiKeyNotice } from "@/components/AiKeyNotice";
import { announceApiKeyError, relay, type ApiKeyErrorPayload } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const MISSING: ApiKeyErrorPayload = {
  error: "api_key_missing", feature: "Vault describe", provider: "deepinfra",
  fix_url: "/settings/ai-keys",
  message: "Vault describe can't run: no DeepInfra API key is set.",
  fix: "Add it in Settings › AI keys.",
};

beforeEach(() => { chatterState.chatter = null; });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("ApiKeyToaster", () => {
  it("shows an owner the message, the fix and the Settings › AI keys link", () => {
    render(<ApiKeyToaster />);
    act(() => announceApiKeyError(MISSING));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(MISSING.message);
    expect(alert).toHaveTextContent(MISSING.fix);
    expect(screen.getByRole("link", { name: /Settings › AI keys/ })).toHaveAttribute("href", "/settings/ai-keys");
  });

  it("shows a chatter the message and who to ask, with no link", () => {
    chatterState.chatter = { chatter_id: 7 };
    render(<ApiKeyToaster />);
    act(() => announceApiKeyError(MISSING));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(MISSING.message);
    expect(alert).toHaveTextContent("Ask your agency owner to add it.");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("dedupes an identical (feature, provider, error) inside the window, not after", () => {
    vi.useFakeTimers();
    render(<ApiKeyToaster />);
    act(() => announceApiKeyError(MISSING));
    act(() => announceApiKeyError(MISSING));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    // A different problem is its own toast.
    act(() => announceApiKeyError({ ...MISSING, error: "api_key_invalid", message: "Vault describe stopped." }));
    expect(screen.getAllByRole("alert")).toHaveLength(2);
    act(() => { vi.advanceTimersByTime(DEDUPE_MS + 1); });
    act(() => announceApiKeyError(MISSING));
    expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(1);
  });

  it("dismisses on the close button", () => {
    render(<ApiKeyToaster />);
    act(() => announceApiKeyError(MISSING));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("AiKeyNotice", () => {
  it("renders the relay's notice from an automation's last_key_error", async () => {
    const invalid: ApiKeyErrorPayload = {
      ...MISSING, error: "api_key_invalid", feature: "Auto Funnel", provider: "deepseek",
      message: "Auto Funnel stopped: DeepSeek rejected the API key (wrong or revoked).",
      fix: "Paste the right key in Settings › AI keys.",
    };
    (relay.get as unknown as Mock).mockResolvedValue({
      account_id: "acc-a",
      items: [{ kind: "reply_mass_funnel", provider: "deepseek", available: true, last_key_error: invalid }],
      notices: [invalid],
    });
    renderWithProviders(<AiKeyNotice accountId="acc-a" kinds={["reply_mass_funnel"]} />);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(invalid.message);
    expect(screen.getByRole("link", { name: /Settings › AI keys/ })).toHaveAttribute("href", "/settings/ai-keys");
    expect((relay.get as unknown as Mock).mock.calls[0][0]).toBe(
      "/admin/ai-key-status?account_id=acc-a&kinds=reply_mass_funnel");
  });

  it("renders nothing when every key is fine", async () => {
    (relay.get as unknown as Mock).mockResolvedValue({ account_id: "acc-a", items: [], notices: [] });
    const { container } = renderWithProviders(<AiKeyNotice accountId="acc-a" kinds={["autoreply"]} />);
    await act(async () => { await Promise.resolve(); });
    expect(container).toBeEmptyDOMElement();
  });
});
