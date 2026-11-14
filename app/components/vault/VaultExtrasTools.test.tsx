/** The Extras drawer's describe "Max": default 2000, persisted per browser, capping the button counts and the press;
 *  and the paused Collect's "continue collecting?" prompt. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";

vi.mock("@/components/AiKeyNotice", () => ({ AiKeyNotice: () => null }));

import VaultExtrasTools from "./VaultExtrasTools";

const sweep = { status: undefined, progress: null, running: false, busy: false, start: async () => {} };

function renderTools(
  plan: { undescribed: number; restage: number },
  collect: { isCollecting?: boolean; collectPaused?: boolean; totalSeen?: number | null;
             onCollectAnswer?: (a: "continue" | "stop") => void } = {},
) {
  const onDescribeAll = vi.fn();
  renderWithProviders(
    <VaultExtrasTools
      accountId="1000001" onClose={() => {}} isCollecting={collect.isCollecting ?? false}
      collectPaused={collect.collectPaused} totalSeen={collect.totalSeen ?? null} cachedCount={10}
      onCollect={() => {}} onCollectAnswer={collect.onCollectAnswer} onDescribeAll={onDescribeAll} describeSweep={sweep}
      describeText={{ label: "", title: "" }} describeStopped={null} harvestSweep={sweep}
      plan={plan as never} capped={false} capReason="" needsReview={0} setNeedsReview={() => {}}
      flagsReviewOpen={false} onOpen={() => {}} download={{ label: "Download full vault", reason: "", onStart: () => {} }}
    />,
  );
  return onDescribeAll;
}

const max = () => screen.getByLabelText("Max items to describe") as HTMLInputElement;

beforeEach(() => window.localStorage.clear());
afterEach(cleanup);

describe("describe Max", () => {
  it("defaults to 2000: counts show the cap, the title says why, the press carries it", () => {
    const onDescribeAll = renderTools({ undescribed: 20000, restage: 300 });
    expect(max().value).toBe("2000");
    const all = screen.getByRole("button", { name: "Describe all (2000)" });
    expect(all.title).toMatch(/describes the 2000 highest-priority items/);
    const rescan = screen.getByRole("button", { name: "Re-scan old (300)" });
    expect(rescan.title).not.toMatch(/highest-priority/);
    fireEvent.click(all);
    fireEvent.click(rescan);
    expect(onDescribeAll.mock.calls).toEqual([["new", 2000], ["restage", 2000]]);
  });

  it("an edit persists; empty = all", () => {
    const onDescribeAll = renderTools({ undescribed: 20000, restage: 300 });
    fireEvent.change(max(), { target: { value: "100" } });
    expect(window.localStorage.getItem("vaultDescribeLimit")).toBe("100");
    expect(screen.getByRole("button", { name: "Re-scan old (100)" })).toBeInTheDocument();
    fireEvent.change(max(), { target: { value: "" } });
    expect(window.localStorage.getItem("vaultDescribeLimit")).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Describe all (20000)" }));
    expect(onDescribeAll).toHaveBeenLastCalledWith("new", 0);
  });

  it("reads the stored value on open", () => {
    window.localStorage.setItem("vaultDescribeLimit", "50");
    renderTools({ undescribed: 20000, restage: 0 });
    expect(max().value).toBe("50");
    expect(screen.getByRole("button", { name: "Describe all (50)" })).toBeInTheDocument();
  });
});

describe("paused collect", () => {
  const plan = { undescribed: 0, restage: 0 };

  it("asks with the count; Continue / Stop answer", () => {
    const onCollectAnswer = vi.fn();
    renderTools(plan, { isCollecting: true, collectPaused: true, totalSeen: 2030, onCollectAnswer });
    expect(screen.getByTestId("vault-collect-paused")).toHaveTextContent("Collected 2030 · continue collecting?");
    expect(screen.getByText(/collect paused 2030/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onCollectAnswer.mock.calls).toEqual([["continue"], ["stop"]]);
  });

  it("a restricted chatter (no totals) still gets the prompt", () => {
    renderTools(plan, { isCollecting: true, collectPaused: true, totalSeen: null, onCollectAnswer: vi.fn() });
    expect(screen.getByTestId("vault-collect-paused")).toHaveTextContent("Collect paused · continue collecting?");
  });

  it.each([
    ["walking", { isCollecting: true, collectPaused: false, totalSeen: 500 }, /collecting… 500/],
    ["finished", { isCollecting: false, collectPaused: false }, /10 cached/],
  ])("no prompt while %s", (_, c, line) => {
    renderTools(plan, { ...c, onCollectAnswer: vi.fn() });
    expect(screen.queryByTestId("vault-collect-paused")).toBeNull();
    expect(screen.getByText(line)).toBeInTheDocument();
  });
});

describe("Inflowwww folders", () => {
  it("opens the folders editor; off for a restricted chatter", () => {
    const onOpen = vi.fn();
    const props = {
      accountId: "1000001", onClose: () => {}, isCollecting: false, totalSeen: null, cachedCount: 0, onCollect: () => {},
      onDescribeAll: () => {}, describeSweep: sweep, describeText: { label: "", title: "" }, describeStopped: null,
      harvestSweep: sweep, plan: undefined, capped: false, capReason: "", needsReview: 0, setNeedsReview: () => {},
      flagsReviewOpen: false, onOpen, download: { label: "Download full vault", reason: "", onStart: () => {} },
    };
    const { rerender } = renderWithProviders(<VaultExtrasTools {...props} />);
    // An empty cache does not turn it off: a folder can be made first.
    fireEvent.click(screen.getByRole("button", { name: "Inflowwww folders" }));
    expect(onOpen).toHaveBeenCalledWith("folders");
    rerender(<VaultExtrasTools {...props} foldersAllowed={false} />);
    expect(screen.getByRole("button", { name: "Inflowwww folders" })).toBeDisabled();
  });
});
