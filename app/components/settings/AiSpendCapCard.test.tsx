/**
 * AiSpendCapCard — Settings › AI keys, a Creator's daily AI spend limit: dollars in the box, cents on the wire,
 * the rest of the stored config echoed (the PUT replaces what it holds), today's per-provider spend shown.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { scope, roster } = vi.hoisted(() => ({
  scope: { accountId: "acc1" as string | null },
  roster: { accounts: [{ id: "acc1", nickname: "Mia", has_session: true }] as Array<{ id: string; nickname: string; has_session: boolean }> },
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => scope }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => roster.accounts }));
vi.mock("@/components/ui/AccountAvatarPicture", () => ({ AccountAvatarPicture: () => null }));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn() } };
});

import AiSpendCapCard from "@/components/settings/AiSpendCapCard";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;

const CONFIG = { persona: "Mia", daily_cost_cap_cents: 100, model: null };

function renderCard(providers: Array<{ provider: string; spent_millicents: number; flagged: boolean }> = []) {
  relayGet.mockResolvedValue({ account_id: "acc1", config: CONFIG, ai_spend_today: { day: "2026-11-11", providers } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AiSpendCapCard /></QueryClientProvider>);
}

const box = () => screen.findByLabelText("Daily AI spend limit in dollars") as Promise<HTMLInputElement>;
const saveBtn = () => screen.getByRole("button", { name: "Save limit" }) as HTMLButtonElement;

afterEach(() => { cleanup(); relayGet.mockReset(); relayPut.mockReset(); });

describe("AiSpendCapCard", () => {
  it("shows the stored cap in dollars and saves dollars as cents with the config echoed", async () => {
    relayPut.mockResolvedValue({ account_id: "acc1", config: { ...CONFIG, daily_cost_cap_cents: 550 } });
    renderCard();
    const input = await box();
    expect(input.value).toBe("1.00");
    expect(saveBtn().disabled).toBe(true);                  // unchanged
    fireEvent.change(input, { target: { value: "5.50" } });
    fireEvent.click(saveBtn());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(relayPut.mock.calls[0]).toEqual(["/admin/account-config",
      { account_id: "acc1", config: { ...CONFIG, daily_cost_cap_cents: 550 } }]);
  });

  it("refuses more than 2 decimals and over $100, and says 0 pauses AI", async () => {
    renderCard();
    const input = await box();
    expect(screen.getByText(/0 pauses all AI for this creator/)).toBeTruthy();
    fireEvent.change(input, { target: { value: "2.555" } });
    expect(saveBtn().disabled).toBe(true);
    expect(screen.getByText("Enter a dollar amount, e.g. 5 or 2.50")).toBeTruthy();
    fireEvent.change(input, { target: { value: "100.01" } });
    expect(saveBtn().disabled).toBe(true);
    expect(screen.getByText("At most $100.00 a day")).toBeTruthy();
    fireEvent.change(input, { target: { value: "0" } });
    expect(saveBtn().disabled).toBe(false);
  });

  it("shows today's spend per provider against the limit", async () => {
    renderCard([{ provider: "deepinfra", spent_millicents: 99, flagged: false },
      { provider: "deepseek", spent_millicents: 4200, flagged: true }]);
    await box();
    expect(screen.getByTestId("ai-cap-spend").textContent).toBe(
      "Today (UTC): DeepInfra <$0.01 · DeepSeek $0.42 (hit the limit) of $1.00 each.");
  });

  it("says when nothing was spent today", async () => {
    renderCard();
    await box();
    expect(screen.getByTestId("ai-cap-spend").textContent).toBe("No AI spend yet today (UTC).");
  });
});
