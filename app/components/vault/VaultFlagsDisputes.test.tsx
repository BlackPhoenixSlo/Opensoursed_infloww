/**
 * The Flags review and Disputes cards: each save is one request (the same call as before), shows "Saving…" while it
 * is out, says why when it fails and lets the operator retry; both cards draw the shared region bits (over lines,
 * meta line, reasons) with the same text. The vault hooks are faked at the module; every name is fake.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

const ITEM = {
  media_id: 31, kind: "photo", iffy: ["edge"], iffy_why: ["waistband at the edge"], lanes: ["AI-tease 10"],
  regions: { breasts_vis: "covered", vulva_vis: "covered", anus_vis: "not_in_frame" },
  over: { vulva_vis: "thong", breasts_vis: "" }, description: "fake still", clothing_state: "lingerie",
  explicitness: "suggestive", codes: [], locked: [], graded: {},
};
const DISPUTE = {
  media_id: 41, kind: "photo", frame_count: 0, codes: [], reasons: ["flags say bare, describe says covered"],
  description: "fake dispute", clothing_state: "topless", explicitness: "explicit", underwear_visible: null,
  regions: { breasts_vis: "bare" }, over: { breasts_vis: "hand" }, resolved: [],
  propose: { flags: { breasts_vis: "bare" }, describe: { breasts_vis: "covered" } },
};

vi.mock("@/hooks/useVaultCache", () => ({
  mirrorFullSrc: (a: string, m: number) => `/img/${a}/${m}`,
  mirrorPosterSrc: (a: string, m: number, f: number) => `/img/${a}/${m}/${f}`,
  gradeFlags: vi.fn(),
  resolveDispute: vi.fn(),
  useFlagsAccuracy: () => ({ data: undefined }),
  useFlagsReview: () => ({
    isLoading: false, error: null, data: { items: [ITEM], total: 1, iffy: 1, prompt_version: 3 },
  }),
  useVaultDisputes: () => ({ isLoading: false, error: null, data: { checked: 5, count: 1, disputes: [DISPUTE] } }),
}));

import VaultDisputesModal from "@/components/vault/VaultDisputesModal";
import VaultFlagsReviewModal from "@/components/vault/VaultFlagsReviewModal";
import { gradeFlags, resolveDispute } from "@/hooks/useVaultCache";
import { renderWithProviders } from "@/test-utils";

const grade = gradeFlags as unknown as Mock;
const resolve = resolveDispute as unknown as Mock;

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
    expect(screen.getByText("thong").parentElement).toHaveTextContent("vulva: thong");
    expect(screen.getByText(/^#31 · photo/)).toHaveTextContent("#31 · photo · suggestive · lingerie · AI-tease 10");
    expect(screen.getByText("waistband at the edge")).toHaveClass("text-warn");
  });

  it("a failed save says why, keeps the card, and a retry sends the same grade", async () => {
    const first = held();
    grade.mockReturnValueOnce(first.p).mockResolvedValueOnce({});
    renderWithProviders(<VaultFlagsReviewModal accountId="acc-1" onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Looks right" }));
    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    first.settle.fail(new Error("relay down"));
    expect(await screen.findByText("relay down")).toHaveClass("text-err");

    fireEvent.click(screen.getByRole("button", { name: "Looks right" }));
    await waitFor(() => expect(screen.queryByText("fake still")).toBeNull());
    expect(grade.mock.calls).toEqual([["acc-1", 31, {}, ""], ["acc-1", 31, {}, ""]]);
  });
});

describe("VaultDisputesModal card", () => {
  it("draws the chip, over line, meta line and reasons", () => {
    renderWithProviders(<VaultDisputesModal accountId="acc-1" onClose={() => {}} />);
    expect(screen.getByText("breasts: bare")).toHaveClass("border-err/50");
    expect(screen.getByText("hand").parentElement).toHaveTextContent("breasts: hand");
    expect(screen.getByText(/^#41 · photo/)).toHaveTextContent("#41 · photo · explicit · topless");
    expect(screen.getByText("flags say bare, describe says covered")).toHaveClass("text-err");
  });

  it("only the picked side says Saving…; a failure says why and both sides come back", async () => {
    const first = held();
    resolve.mockReturnValueOnce(first.p).mockResolvedValueOnce({});
    renderWithProviders(<VaultDisputesModal accountId="acc-1" onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Describe was right/ }));
    await screen.findByText("Saving…");
    expect(screen.getByRole("button", { name: /Flags were right/ })).toBeDisabled();
    first.settle.fail(new Error("relay down"));
    expect(await screen.findByText("relay down")).toHaveClass("text-err");
    expect(screen.getByRole("button", { name: /Flags were right/ })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /Flags were right/ }));
    await waitFor(() => expect(screen.queryByText("fake dispute")).toBeNull());
    expect(resolve.mock.calls).toEqual([
      ["acc-1", 41, { breasts_vis: "covered" }],
      ["acc-1", 41, { breasts_vis: "bare" }],
    ]);
  });
});
