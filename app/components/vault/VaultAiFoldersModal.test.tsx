/**
 * VaultAiFoldersModal's build and flags-pass requests: a failed build says why and an option change keeps that
 * error; a landed build shows its result until an option changes; the flags pass shows its own error. Same calls
 * as before. The vault hooks are faked at the module; every name is fake.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

const plan = vi.hoisted(() => ({ flagsReady: true }));
vi.mock("@/hooks/useVaultCache", () => ({
  mirrorThumbSrc: () => "",
  applyAiFolders: vi.fn(),
  runVaultFlags: vi.fn(),
  useVaultFlagsStatus: () => ({ data: undefined, dataUpdatedAt: 0 }),
  useAiFolderPlan: () => ({
    isLoading: false, isError: false, isFetching: false, refetch: () => {},
    data: {
      account_id: "acc-1", keep: 2, solo: false, shoots_found: 1, solo_coverage: null,
      folders: [{ name: "AI-tease 10", source: "lane", purpose: "tease", size: 0, kinds: {}, tiers: {},
        closes_on_own: 0, items: [], solo: false }],
      summary: { folders: 1, scripts: 0, lanes: 1, solo_cuts: 0, unique_media: 0, memberships: 0 },
      flags: { stills: 10, flagged: plan.flagsReady ? 10 : 4, missing: plan.flagsReady ? 0 : 6, ready: plan.flagsReady },
    },
  }),
}));

import VaultAiFoldersModal from "@/components/vault/VaultAiFoldersModal";
import { applyAiFolders, runVaultFlags } from "@/hooks/useVaultCache";
import { renderWithProviders } from "@/test-utils";

const apply = vi.mocked(applyAiFolders);
const runFlags = vi.mocked(runVaultFlags);
const RESULT = { folders: 1, new: 1, reused: 0, items: 3, of_mirrored: 1, of_failed: 0, created: [] };

afterEach(() => { cleanup(); vi.clearAllMocks(); plan.flagsReady = true; });

describe("VaultAiFoldersModal", () => {
  it("a failed build says why, an option change keeps it; a landed build shows until an option changes", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    apply.mockRejectedValueOnce(new Error("relay down")).mockResolvedValueOnce(RESULT);
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Create 1 folders" }));
    expect(await screen.findByText("relay down")).toHaveClass("text-err");
    fireEvent.click(screen.getByRole("switch", { name: "Solo cut of each lane" }));
    expect(screen.getByText("relay down")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create 1 folders" }));
    expect(await screen.findByText(/Created 1 new/)).toBeInTheDocument();
    expect(screen.queryByText("relay down")).toBeNull();
    expect(screen.getByRole("button", { name: "Rebuild" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Also create on OnlyFans" }));
    expect(screen.queryByText(/Created 1 new/)).toBeNull();
    expect(screen.getByRole("button", { name: "Create 1 folders" })).toBeInTheDocument();
    expect(apply.mock.calls).toEqual([
      ["acc-1", { keep: 2, solo: false, mirrorToOf: true }],
      ["acc-1", { keep: 2, solo: true, mirrorToOf: true }],
    ]);
  });

  it("the flags pass shows its own failure", async () => {
    plan.flagsReady = false;
    runFlags.mockRejectedValueOnce(new Error("flags busy"));
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getByRole("button", { name: "Create 1 folders" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Check 6 stills" }));
    await waitFor(() => expect(screen.getByText("flags busy")).toHaveClass("text-err"));
    expect(runFlags).toHaveBeenCalledWith("acc-1");
  });

  it("disables the flags pass while its request is pending", async () => {
    plan.flagsReady = false;
    let finish!: () => void;
    runFlags.mockImplementationOnce(() => new Promise((resolve) => {
      finish = () => resolve({ status: "running", candidates: 6, already: false });
    }));
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    const button = screen.getByRole("button", { name: "Check 6 stills" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    expect(runFlags).toHaveBeenCalledTimes(1);
    finish();
    await waitFor(() => expect(button).toBeEnabled());
  });
});
