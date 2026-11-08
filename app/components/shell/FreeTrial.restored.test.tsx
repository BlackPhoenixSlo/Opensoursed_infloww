/**
 * The expired-trial nag on a real React Query cache holding a restored Applied
 * answer (the IndexedDB snapshot, fresh for its 60 s staleTime): the nag waits
 * for this mount's own read and follows it, never the restored answer.
 */
import { dehydrate, hydrate, IsRestoringProvider, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const owner = { user_id: "u1", username: "owner", created_at: new Date(Date.now() - 10 * 86_400_000).toISOString() };
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: owner }), useOptionalUser: () => ({ user: owner }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null }), useOptionalChatter: () => ({ chatter: null }) }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
const get = vi.fn();
vi.mock("@/lib/relay", () => ({ relay: { get: (...a: unknown[]) => get(...a) } }));

import { FreeTrialExpiredModal } from "@/components/shell/FreeTrial";

const answer = (hide: boolean) => ({ preferences: { tz: null, report_tz: null, week_start: "monday", hide_trial_popup: hide } });

/** A cache as the snapshot restores it: the Applied answer `restored`, just fetched. */
function mount(restored: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["applied-settings", "u1", null], answer(restored));
  render(<QueryClientProvider client={qc}><FreeTrialExpiredModal /></QueryClientProvider>);
}

const dialog = () => screen.queryByRole("dialog", { name: "Free trial exceeded" });

afterEach(() => {
  cleanup();
  get.mockReset();
});

describe("FreeTrialExpiredModal over a restored Applied answer", () => {
  it.each([
    { restored: false, server: true, shown: false },
    { restored: false, server: false, shown: true },
    { restored: true, server: false, shown: true },
    { restored: true, server: true, shown: false },
  ])("restored $restored, server $server: shown $shown", async ({ restored, server, shown }) => {
    let answerNow!: () => void;
    get.mockImplementation(() => new Promise((res) => { answerNow = () => res(answer(server)); }));
    mount(restored);
    // The restored answer alone decides nothing: no nag before this mount's read lands.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(get).toHaveBeenCalledWith("/admin/settings/applied", { accountId: null });
    expect(dialog()).toBeNull();
    answerNow();
    if (shown) await waitFor(() => expect(dialog()).toBeInTheDocument());
    else {
      await new Promise((r) => setTimeout(r, 50));
      expect(dialog()).toBeNull();
    }
  });

  it("a failed read shows the nag", async () => {
    get.mockRejectedValue(new Error("502"));
    mount(true);
    await waitFor(() => expect(dialog()).toBeInTheDocument());
  });

  // The real providers: the IndexedDB restore lands AFTER mount (children render while
  // restoring) and copies the saved fetch count, so "fetched since mount" alone would trust it.
  it.each([
    { server: true, shown: false },
    { server: false, shown: true },
  ])("snapshot restored after mount (hide off), server $server: shown $shown", async ({ server, shown }) => {
    let answerNow!: () => void;
    get.mockImplementation(() => new Promise((res) => { answerNow = () => res(answer(server)); }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tree = (restoring: boolean) => (
      <QueryClientProvider client={qc}>
        <IsRestoringProvider value={restoring}><FreeTrialExpiredModal /></IsRestoringProvider>
      </QueryClientProvider>
    );
    const { rerender } = render(tree(true));
    const saved = new QueryClient();
    saved.setQueryData(["applied-settings", "u1", null], answer(false), { updatedAt: Date.now() - 5_000 });
    act(() => hydrate(qc, dehydrate(saved)));
    await new Promise((r) => setTimeout(r, 20));
    expect(dialog()).toBeNull();
    rerender(tree(false));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(dialog()).toBeNull();
    answerNow();
    if (shown) await waitFor(() => expect(dialog()).toBeInTheDocument());
    else {
      await new Promise((r) => setTimeout(r, 50));
      expect(dialog()).toBeNull();
    }
  });
});
