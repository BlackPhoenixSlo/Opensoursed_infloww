/**
 * The Jev v8 flags opt-in (Vault › Extras):
 *  1. reads `vault_jev_enabled` off the account config (off by default);
 *  2. a toggle PUTs the stored config back with only that key changed;
 *  3. on, but the server cannot run it (no NudeNet / key) → the refusal reason shows.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn() } };
});

import VaultJevToggle, { type JevPlan } from "@/components/vault/VaultJevToggle";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const ACC = "900001";
const CONFIG = { persona: "Ella.", daily_cost_cap_cents: 100, cotag_tag_videos: false };

function renderToggle(config: Record<string, unknown>, jev?: JevPlan) {
  relayGet.mockResolvedValue({ account_id: ACC, config });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  render(<VaultJevToggle accountId={ACC} jev={jev} />, { wrapper });
}

afterEach(() => { cleanup(); relayGet.mockReset(); relayPut.mockReset(); });

describe("VaultJevToggle", () => {
  it("is off by default and turning it on saves only that key", async () => {
    renderToggle(CONFIG);
    const sw = await screen.findByRole("switch", { name: "Jev v8 flags" });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    relayPut.mockResolvedValue({ account_id: ACC, config: { ...CONFIG, vault_jev_enabled: true } });
    fireEvent.click(sw);
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(relayPut.mock.calls[0]).toEqual(["/admin/account-config",
      { account_id: ACC, config: { ...CONFIG, vault_jev_enabled: true } }]);
  });

  it("shows on, and the server's refusal reason when it cannot run", async () => {
    renderToggle({ ...CONFIG, vault_jev_enabled: true },
                 { enabled: true, ready: false, reason: "NUDENET_640M_PATH is not set" });
    const sw = await screen.findByRole("switch", { name: "Jev v8 flags" });
    expect(sw.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/NUDENET_640M_PATH is not set/)).toBeTruthy();
  });

  it("says nothing extra when ready", async () => {
    renderToggle({ ...CONFIG, vault_jev_enabled: true }, { enabled: true, ready: true, reason: "" });
    await screen.findByRole("switch", { name: "Jev v8 flags" });
    expect(screen.queryByText(/refusing/)).toBeNull();
  });
});
