/**
 * The Creator's two vault switches: both off until tapped, one PUT per tap, and the Set price modal's promise
 * follows "Folder price is final" (off: the old line; on: the saved price cannot be changed).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";

const h = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/components/vault/VaultAccount", () => ({ useVaultAccountId: () => "1000001" }));
vi.mock("@/lib/relay", async (orig) => {
  const mod = await orig<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: h.get, put: h.put } };
});

import { FolderPriceModal } from "@/components/vault/VaultFolderRail";
import VaultSettingsSwitches from "@/components/vault/VaultSettingsSwitches";

const OFF = { folder_price_final: false, standard_folders: false };

beforeEach(() => {
  h.get.mockReset();
  h.put.mockReset();
});
afterEach(cleanup);

describe("VaultSettingsSwitches", () => {
  it("shows both switches off and saves one tap as one PUT", async () => {
    h.get.mockResolvedValue({ account_id: "1000001", ...OFF });
    h.put.mockResolvedValue({ account_id: "1000001", ...OFF, folder_price_final: true });
    renderWithProviders(<VaultSettingsSwitches accountId="1000001" />);
    const price = await screen.findByRole("switch", { name: "Folder price is final" });
    const standard = screen.getByRole("switch", { name: "Standard folders" });
    expect(price).toHaveAttribute("aria-checked", "false");
    expect(standard).toHaveAttribute("aria-checked", "false");
    fireEvent.click(price);
    await waitFor(() => expect(price).toHaveAttribute("aria-checked", "true"));
    expect(h.put).toHaveBeenCalledTimes(1);
    expect(h.put.mock.calls[0].slice(0, 2)).toEqual(
      ["/admin/vault-ai/settings", { account_id: "1000001", folder_price_final: true }]);
    expect(standard).toHaveAttribute("aria-checked", "false");
  });

  it("a failed save says so and leaves the switch as it was", async () => {
    h.get.mockResolvedValue({ account_id: "1000001", ...OFF });
    h.put.mockRejectedValue(new Error("500"));
    renderWithProviders(<VaultSettingsSwitches accountId="1000001" />);
    const price = await screen.findByRole("switch", { name: "Folder price is final" });
    fireEvent.click(price);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save. Try again.");
    expect(price).toHaveAttribute("aria-checked", "false");
  });

  it("renders nothing when the read is refused (a folder-limited chatter)", async () => {
    h.get.mockRejectedValue(new Error("403"));
    const { container } = renderWithProviders(<VaultSettingsSwitches accountId="1000001" />);
    await waitFor(() => expect(h.get).toHaveBeenCalled());
    expect(container.querySelector("[data-testid=vault-settings-switches]")).toBeNull();
  });
});

describe("FolderPriceModal", () => {
  const modal = () => renderWithProviders(
    <FolderPriceModal name="Beach" priceRef="of:1" current={null} onSave={async () => {}} onCancel={() => {}} />);

  it("off: keeps the old line", async () => {
    h.get.mockResolvedValue({ account_id: "1000001", ...OFF });
    modal();
    await waitFor(() => expect(h.get).toHaveBeenCalled());
    expect(screen.getByText(/Full AI Chat sells the items in/)).toBeInTheDocument();
    expect(screen.queryByText(/haggling cannot change it/)).toBeNull();
  });

  it("on: says the saved price is final", async () => {
    h.get.mockResolvedValue({ account_id: "1000001", ...OFF, folder_price_final: true });
    modal();
    expect(await screen.findByText(/AI pricing and haggling cannot change it/)).toBeInTheDocument();
    expect(screen.queryByText(/Full AI Chat sells the items in/)).toBeNull();
  });
});
