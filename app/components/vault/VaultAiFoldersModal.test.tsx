/**
 * VaultAiFoldersModal's build and flags-pass requests: a failed build says why and an option change keeps that
 * error; a landed build shows its result until an option changes; the flags pass shows its own error. Unchecked
 * stills only inform (the server leaves them out of safe explicit, $10 and $50), never block; zero folders does. The vault hooks are faked at the module; every name is fake.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

const plan = vi.hoisted(() => ({ flagsReady: true, noFolders: false, retireOnOf: 0, jevOn: true }));
vi.mock("@/hooks/useVaultCache", () => ({
  mirrorThumbSrc: () => "",
  applyAiFolders: vi.fn(),
  runVaultFlags: vi.fn(),
  useVaultFlagsStatus: () => ({ data: undefined, dataUpdatedAt: 0 }),
  useAiFolderPlan: () => ({
    isLoading: false, isError: false, isFetching: false, refetch: () => {},
    data: {
      account_id: "acc-1", keep: 2, solo: false, shoots_found: 1, solo_coverage: null,
      folders: plan.noFolders ? [] : [{ name: "AI-tease 10", source: "lane", purpose: "tease", size: 0, kinds: {},
        tiers: {}, closes_on_own: 0, items: [], solo: false }],
      summary: { folders: plan.noFolders ? 0 : 1, scripts: 0, lanes: 1, topics: 0, solo_cuts: 0, unique_media: 0,
        memberships: 0 },
      topics: [],
      jev: { enabled: plan.jevOn, photos: 10, with_jev: plan.jevOn ? 7 : 0 },
      topic_catalogue: [
        { slug: "spread", name: "spread", description: "legs spread", price: "split", count: 3 },
        { slug: "bikini", name: "bikini", description: "in swimwear", price: "split", count: 2 },
        { slug: "feet", name: "feet", description: "feet the subject", price: "rung", count: 4, group: "feet" },
      ],
      flags: { stills: 10, flagged: plan.flagsReady ? 10 : 4, missing: plan.flagsReady ? 0 : 6, ready: plan.flagsReady },
      changes: {
        create: plan.noFolders ? 0 : 1, keep: 0, retire: plan.retireOnOf ? 2 : 0, retire_on_of: plan.retireOnOf,
        retired: plan.retireOnOf ? [{ folder_id: 7, name: "AI-old on OF", of_list_id: 77 },
          { folder_id: 8, name: "AI-old local", of_list_id: null }] : [],
      },
    },
  }),
}));

import VaultAiFoldersModal from "@/components/vault/VaultAiFoldersModal";
import { applyAiFolders, runVaultFlags } from "@/hooks/useVaultCache";
import { renderWithProviders } from "@/test-utils";

const apply = vi.mocked(applyAiFolders);
const runFlags = vi.mocked(runVaultFlags);
const RESULT = { folders: 1, new: 1, reused: 0, items: 3, of_mirrored: 1, of_failed: 0, created: [] };

afterEach(() => { cleanup(); vi.clearAllMocks(); plan.flagsReady = true; plan.noFolders = false; plan.retireOnOf = 0;
  plan.jevOn = true; });

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
      ["acc-1", { keep: 2, solo: false, mirrorToOf: true, topics: [] }],
      ["acc-1", { keep: 2, solo: true, mirrorToOf: true, topics: [] }],
    ]);
  });

  it("previews create / keep / retire before Confirm; retiring OF-linked folders shows on the button", async () => {
    plan.retireOnOf = 1;
    apply.mockResolvedValueOnce(RESULT);
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getByText("Confirm will create 1 · keep 0 · retire 2")).toBeInTheDocument();
    expect(screen.getByText(/Retiring AI-old on OF, AI-old local/)).toBeInTheDocument();
    expect(screen.getByText(/1 of them is linked to an OnlyFans list/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create 1 folders · retire 1 linked to OnlyFans" }));
    expect(await screen.findByText(/Created 1 new/)).toBeInTheDocument();
  });

  it("keep offers 0 (lanes only) to 20 and sends 0 as 0", async () => {
    apply.mockResolvedValueOnce(RESULT);
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    const select = screen.getByLabelText("Keep as scripts");
    expect(select.querySelectorAll("option")).toHaveLength(21);
    fireEvent.change(select, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Create 1 folders" }));
    await waitFor(() => expect(apply).toHaveBeenCalledWith("acc-1", { keep: 0, solo: false, mirrorToOf: true, topics: [] }));
  });

  it("topic folders: none ticked by default; ticked ones (Select all / None) go in the build", async () => {
    apply.mockResolvedValueOnce(RESULT);
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getByText("7 of 10 photos have Jev data")).toBeInTheDocument();
    const bikini = screen.getByRole("checkbox", { name: /bikini/ });
    expect(bikini).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getByRole("checkbox", { name: /spread/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^feet/ })).not.toBeChecked();   // feet is its own opt-in
    fireEvent.click(screen.getByRole("button", { name: "None" }));
    expect(bikini).not.toBeChecked();
    fireEvent.click(bikini);
    fireEvent.click(screen.getByRole("button", { name: "Create 1 folders" }));
    await waitFor(() => expect(apply).toHaveBeenCalledWith("acc-1",
      { keep: 2, solo: false, mirrorToOf: true, topics: ["bikini"] }));
  });

  it("feet is its own group, off by default; ticking it sends the feet slug", async () => {
    apply.mockResolvedValueOnce(RESULT);
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    const group = screen.getByTestId("ai-folders-feet");
    expect(group).toHaveTextContent("Feet");
    expect(group).toHaveTextContent("AI-feet tease / nude / nude-body");
    const feet = within(group).getByRole("checkbox", { name: /^feet/ });
    expect(feet).not.toBeChecked();
    fireEvent.click(feet);
    fireEvent.click(screen.getByRole("button", { name: "Create 1 folders" }));
    await waitFor(() => expect(apply).toHaveBeenCalledWith("acc-1",
      { keep: 2, solo: false, mirrorToOf: true, topics: ["feet"] }));
  });

  it("topic folders without Jev data: the hint shows and the boxes are disabled", () => {
    plan.jevOn = false;
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getByText(/Needs Jev classification/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /bikini/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Select all" })).toBeDisabled();
  });

  it("the flags pass shows its own failure", async () => {
    plan.flagsReady = false;
    runFlags.mockRejectedValueOnce(new Error("flags busy"));
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Check 6 stills" }));
    await waitFor(() => expect(screen.getByText("flags busy")).toHaveClass("text-err"));
    expect(runFlags).toHaveBeenCalledWith("acc-1");
  });

  it("unchecked stills inform but never block Create", async () => {
    plan.flagsReady = false;
    apply.mockResolvedValueOnce(RESULT);
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getByText("6 of 10 stills not checked yet")).toBeInTheDocument();
    expect(screen.getByText(/left out of the\s+safe-explicit, \$10 and \$50 folders/)).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Create 1 folders" });
    expect(create).toBeEnabled();
    fireEvent.click(create);
    expect(await screen.findByText(/Created 1 new/)).toBeInTheDocument();
  });

  it("all checked: no flags box; zero folders: Create disabled", () => {
    plan.noFolders = true;
    renderWithProviders(<VaultAiFoldersModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.queryByText(/not checked yet/)).toBeNull();
    expect(screen.getByRole("button", { name: "Create 0 folders" })).toBeDisabled();
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
