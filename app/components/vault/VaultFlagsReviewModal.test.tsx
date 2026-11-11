/**
 * The Flags review card: each save is one request, shows "Saving…" while it is out, says why when it fails and lets
 * the operator retry; it draws the shared region bits (over lines, meta line, reasons) and, for an item the two passes
 * disagree on, the auto-settled reading. The vault hooks are faked at the module; every name is fake.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

const ITEM = {
  media_id: 31, kind: "photo", iffy: ["edge"], iffy_why: ["waistband at the edge"], lanes: ["AI-tease 10"],
  regions: { breasts_vis: "covered", vulva_vis: "covered", anus_vis: "not_in_frame" },
  over: { vulva_vis: "thong", breasts_vis: "" }, description: "fake still", clothing_state: "lingerie",
  explicitness: "suggestive", codes: [], settled: [], settled_price: 0, locked: [], graded: {},
};
const DISPUTED = {
  ...ITEM, media_id: 32, description: "fake disputed still", codes: ["nude_but_clothed"],
  iffy: ["passes_disagree"], iffy_why: ["the two passes disagree"], settled_price: 10,
  settled: ["describe said fully nude, flags name a garment: read as pulled_down", "never in a free lane"],
};

vi.mock("@/hooks/useVaultCache", () => ({
  gradeFlags: vi.fn(),
  useFlagsAccuracy: () => ({ data: undefined }),
  useFlagsReview: () => ({
    isLoading: false, error: null, data: { items: [ITEM, DISPUTED], total: 2, iffy: 2, prompt_version: 3 },
  }),
}));

import VaultFlagsReviewModal from "@/components/vault/VaultFlagsReviewModal";
import { gradeFlags } from "@/hooks/useVaultCache";
import { renderWithProviders } from "@/test-utils";

const grade = gradeFlags as unknown as Mock;

afterEach(() => { cleanup(); vi.clearAllMocks(); });

/** A promise the test settles by hand. */
function held() {
  let settle!: { ok: () => void; fail: (e: Error) => void };
  const p = new Promise<void>((ok, fail) => { settle = { ok: () => ok(), fail }; });
  return { p, settle };
}

describe("VaultFlagsReviewModal card", () => {
  it("draws the over line, meta line with lanes, and the reasons", () => {
    renderWithProviders(<VaultFlagsReviewModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getAllByText("thong")[0].parentElement).toHaveTextContent("vulva: thong");
    expect(screen.getByText(/^#31 · photo/)).toHaveTextContent("#31 · photo · suggestive · lingerie · AI-tease 10");
    expect(screen.getByText("waistband at the edge")).toHaveClass("text-warn");
  });

  it("a disputed item shows the reading it was auto-settled to; an agreed one shows none", () => {
    renderWithProviders(<VaultFlagsReviewModal accountId="acc-1" onClose={() => {}} />);
    const lists = screen.getAllByRole("list", { name: "Auto-settled reading" });
    expect(lists).toHaveLength(1);
    expect(within(lists[0]).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Auto-settled at $10",
      "Auto-settled: describe said fully nude, flags name a garment: read as pulled_down",
      "Auto-settled: never in a free lane",
    ]);
  });

  it("there is no way to pick a side by hand any more", () => {
    renderWithProviders(<VaultFlagsReviewModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: /Flags were right|Describe was right|Fix disagreements/ })).toBeNull();
  });

  it("a failed save says why, keeps the card, and a retry sends the same grade", async () => {
    const first = held();
    grade.mockReturnValueOnce(first.p).mockResolvedValueOnce({});
    renderWithProviders(<VaultFlagsReviewModal accountId="acc-1" onClose={() => {}} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Looks right" })[0]);
    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    first.settle.fail(new Error("relay down"));
    expect(await screen.findByText("relay down")).toHaveClass("text-err");

    fireEvent.click(screen.getAllByRole("button", { name: "Looks right" })[0]);
    await waitFor(() => expect(screen.queryByText("fake still")).toBeNull());
    expect(grade.mock.calls).toEqual([["acc-1", 31, {}, ""], ["acc-1", 31, {}, ""]]);
  });
});
