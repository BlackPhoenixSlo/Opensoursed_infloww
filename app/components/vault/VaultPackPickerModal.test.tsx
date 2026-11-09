/**
 * VaultPackPickerModal: unsaved verdicts are not dropped by Done or Escape (only the ×, a discard, closes while
 * dirty); a failed Save says so and keeps the verdicts; Publish to OF asks in an IfModal before the same request.
 * The vault hooks are faked at the module (the candidates query and the two writes); every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/hooks/useVaultCache", () => ({
  mirrorFullSrc: (a: string, m: number) => `/img/${a}/${m}`,
  savePackTriage: vi.fn(),
  publishFolderToOf: vi.fn(),
  usePackCandidates: () => ({
    isLoading: false,
    error: null,
    data: {
      category: "feet",
      rungs: ["tease", "nude", "nude-body"],
      folders: [
        { rung: "tease", name: "feet-tease", folder_id: 11, count: 2, of_list_id: null },
        { rung: "nude", name: "feet-nude", folder_id: 12, count: 1, of_list_id: null },
        { rung: "nude-body", name: "feet-body", folder_id: null, count: 0, of_list_id: null },
      ],
      candidates: [
        { media_id: 1, kind: "photo", rung: null, description: "one" },
        { media_id: 2, kind: "photo", rung: null, description: "two" },
      ],
      filed: 0,
    },
  }),
}));

import VaultPackPickerModal from "@/components/vault/VaultPackPickerModal";
import { publishFolderToOf, savePackTriage } from "@/hooks/useVaultCache";
import { renderWithProviders } from "@/test-utils";

const save = savePackTriage as unknown as Mock;
const publish = publishFolderToOf as unknown as Mock;

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

function mount() {
  const onClose = vi.fn();
  renderWithProviders(<VaultPackPickerModal accountId="acc-1" onClose={onClose} />);
  return onClose;
}
const btn = (name: string | RegExp) => screen.getByRole("button", { name });
/** Rule candidate "one" onto the tease rung: one unsaved verdict. */
const ruleOne = () => fireEvent.click(within(screen.getByText("one").parentElement!).getByRole("button", { name: "tease" }));

describe("VaultPackPickerModal with unsaved verdicts", () => {
  it("Done is off and Escape does nothing; the × still closes", () => {
    const onClose = mount();
    expect(btn("Done")).not.toBeDisabled();
    ruleOne();
    expect(btn("Save 1")).not.toBeDisabled();
    expect(btn("Done")).toBeDisabled();
    expect(btn("Done")).toHaveAttribute("title", "Save or discard first");
    fireEvent.click(btn("Done"));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(btn("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a failed Save says so in the status bar and keeps the verdicts to retry", async () => {
    save.mockRejectedValueOnce(new Error("relay down"));
    mount();
    ruleOne();
    fireEvent.click(btn("Save 1"));
    await waitFor(() => expect(screen.getByText("save failed: relay down")).toBeInTheDocument());
    expect(screen.getByText("save failed: relay down")).toHaveClass("text-err");
    expect(save).toHaveBeenCalledWith("acc-1", "feet", [{ media_id: 1, rung: "tease" }]);
    expect(btn("Save 1")).not.toBeDisabled();
  });
});

describe("VaultPackPickerModal Publish to OF", () => {
  it("asks first; Cancel sends nothing, Publish sends one request per stocked rung", async () => {
    publish.mockImplementation(async (_a: string, folderId: number) => ({
      folder_id: folderId, name: `f${folderId}`, of_list_id: 900 + folderId, created: true, pushed: 1, synced: 1,
      stale_on_of: [],
    }));
    mount();
    fireEvent.click(btn("Publish to OF (2)"));
    const ask = await screen.findByRole("dialog", { name: "Create 2 REAL folder(s) in the OnlyFans vault?" });
    expect(ask).toHaveTextContent("feet-tease — 2 items");
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    expect(publish).not.toHaveBeenCalled();

    fireEvent.click(btn("Publish to OF (2)"));
    fireEvent.click(within(await screen.findByRole("dialog", { name: /REAL folder/ })).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(publish).toHaveBeenCalledTimes(2));
    expect(publish.mock.calls).toEqual([["acc-1", 11], ["acc-1", 12]]);
    await waitFor(() => expect(screen.getByText(/f11 → OF list 911/)).toBeInTheDocument());
  });
});
