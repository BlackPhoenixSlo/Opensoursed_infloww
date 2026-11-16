import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test-utils";
import type { StandardFolder } from "@/hooks/useStandardFolders";
import VaultStandardFolders from "./VaultStandardFolders";

const h = vi.hoisted(() => ({ save: vi.fn().mockResolvedValue(undefined) }));
vi.mock("@/components/vault/VaultAccount", () => ({ useVaultAccountId: () => "creator-a" }));
vi.mock("@/hooks/useFolderPrices", () => ({
  useFolderPrices: () => ({ data: { "vf:11": 2500 } }),
  setFolderPrice: (...args: unknown[]) => h.save(...args),
}));
const folders: StandardFolder[] = [
  { id: 11, kind: "photo", slug: "bikini", name: "Bikini", items: 4, priceable: true },
  { id: 12, kind: "photo", slug: "uncategorised", name: "Uncategorised / Needs Review", items: 2, priceable: false },
  { id: 21, kind: "video", slug: "bikini", name: "Bikini", items: 3, priceable: true },
];
afterEach(() => { cleanup(); h.save.mockClear(); });
const props = { accountId: "creator-a", folders, selectedId: null, pending: 6,
  syncing: false, error: false, onRefresh: vi.fn() };

describe("standard category controls", () => {
  it("selects the correct media group, shows pending, and gives review no price control", () => {
    const select = vi.fn();
    renderWithProviders(<VaultStandardFolders {...props} onSelect={select} />);
    fireEvent.click(screen.getByRole("button", { name: "Open Videos / Bikini" }));
    expect(select).toHaveBeenCalledWith(folders[2]);
    expect(screen.getByText(/6 awaiting description/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set price for.*Needs Review/ })).not.toBeInTheDocument();
  });
  it("saves a price to the stable internal folder reference", async () => {
    renderWithProviders(<VaultStandardFolders {...props} onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Set price for Photos / Bikini" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "35" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(h.save).toHaveBeenCalledWith(expect.anything(),
      { account_id: "creator-a", ref: "vf:11", price_cents: 3500 }));
  });
  it("mobile selection uses an internal ID, including when names match", () => {
    const select = vi.fn();
    renderWithProviders(<VaultStandardFolders {...props} mobile onSelect={select} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Standard category" }), { target: { value: "21" } });
    expect(select).toHaveBeenCalledWith(folders[2]);
  });
});
