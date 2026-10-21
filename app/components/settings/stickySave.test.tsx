/**
 * The pinned Save bar.
 *
 * The automation tabs are tall, so each tab grew a SECOND Save pinned to
 * the bottom of the viewport. The in-flow row stays exactly where it was; this
 * is additive.
 *
 * Three properties are worth a test and two of them guard against writing
 * something the operator did not ask for:
 *
 *   • The pin reads the SAME gate as the in-flow button. A save on a FAILED or
 *     EMPTY load posts a sparse blob that REPLACES the account's stored config.
 *     A pinned button that skipped that gate would wipe an account's settings
 *     with one click from a convenience control. That is the case pinned
 *     hardest below, and it is asserted on the WIRE — a `disabled` attribute
 *     that looks right while a PUT still goes out is precisely the failure that
 *     matters.
 *
 *     It is asserted on NudgeOnlineTab's PLACEMENT — its bar lives outside the
 *     `isLoading ? … : <Card>` ternary that holds the form, so it is on screen
 *     at a moment when the in-flow button does not exist at all, and a gate that
 *     only watched the mutations was wide open there.
 *
 *   • That gate covers EVERY store the save writes, and covers each of them for
 *     the right window. NudgeOnlineTab writes two: the config blob and an
 *     automation RULE, and the rule list is a second query with its own
 *     lifetime — with it still in flight `rule` is null, so a save creates a
 *     duplicate detector instead of editing the one already there. The mirror
 *     matters just as much: that list POLLS, so the gate reads `data !==
 *     undefined` and not `isSuccess`, or one failed background refetch would
 *     take both Save controls away mid-edit. Both directions are asserted.
 *
 *   • It fires the same mutation as the in-flow button, not a copy of the save
 *     logic that can drift.
 *
 * The bar is addressed by `data-testid`, never by role+name: its accessible name
 * is deliberately identical to the in-flow twin's, so a name lookup cannot tell
 * the two apart. `inFlowSave()` / `pinnedSave()` in app/test-utils.tsx say which
 * one a case means.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn() },
  };
});

const ACCT = "123456789";

// NudgeOnlineTab picks its own account off the signed-in owner's list rather
// than taking one as a prop, and that list is behind the user/chatter contexts.
// Only the one selector is replaced; everything else in the module is the real
// thing.
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return {
    ...mod,
    useActiveAccounts: () => [{ id: ACCT, nickname: "acct", has_session: true }],
  };
});

import NudgeOnlineTab from "@/components/settings/NudgeOnlineTab";
import { relay } from "@/lib/relay";
import { inFlowSave, pinnedSave } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** The same wrapper, but bound to a client the CASE can reach — the only way to
 *  drive a background refetch by hand instead of waiting 30s for the poll. */
function wrapperFor(qc: QueryClient) {
  return function Bound({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the pinned Save bar", () => {
  const SAVE = /Save changes/i;
  const RULE = {
    id: 7, account_id: ACCT, name: "Nudge online", kind: "nudge_online",
    is_enabled: true, every_seconds: 60, trigger: { type: "cadence" },
    payload: {}, quiet_hours: null, created_at: null, last_run: null,
    next_due_at: null, has_pending_job: false,
  };
  function loaded() {
    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/nudge-config")) {
        return { account_id: ACCT, config: { enabled: true }, defaults: {} };
      }
      if (path.startsWith("/admin/automation-rules")) return { rules: [RULE] };
      return {};
    });
  }

  it("is there on a tab that saves, alongside the in-flow row it duplicates", async () => {
    loaded();
    render(<NudgeOnlineTab />, { wrapper });

    // Both exist. The in-flow row was NOT relocated to make room for the pin.
    await waitFor(() => expect(pinnedSave(SAVE).button).not.toBeDisabled());
    expect(screen.getAllByRole("button", { name: SAVE }).length).toBeGreaterThanOrEqual(2);
    expect(inFlowSave(SAVE)).toBeTruthy();
  });

  it("fires the SAME mutation as the in-flow button", async () => {
    loaded();
    relayPut.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(pinnedSave(SAVE).button).not.toBeDisabled());
    await user.click(pinnedSave(SAVE).button);
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    const fromPin = relayPut.mock.calls.at(-1);

    relayPut.mockClear();
    await waitFor(() => expect(inFlowSave(SAVE)).not.toBeDisabled());
    await user.click(inFlowSave(SAVE));
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    const fromRow = relayPut.mock.calls.at(-1);

    // Same endpoint, same body — one handler, not two copies of the save logic.
    expect(fromPin![0]).toEqual(fromRow![0]);
    expect(fromPin![1]).toEqual(fromRow![1]);
  });
});

describe("the pinned Save bar, on a tab whose form is behind a loading branch", () => {
  const CREATE = /Create automation/i;

  /** `/admin/nudge-config` never settles, so `cfgQ.isLoading` stays true and the
   *  tab renders "Loading…" in place of its form for the whole test. */
  function stallTheConfig() {
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith("/admin/nudge-config")) return new Promise(() => {});
      return Promise.resolve({ rules: [] });
    });
  }

  it("🚨 is on screen DURING the fetch, disabled, and sends NOTHING", async () => {
    // THE PLACEMENT CASE. NudgeOnlineTab wraps its whole form in
    // `cfgQ.isLoading ? <div>Loading…</div> : <Card>…</Card>`, and the pinned
    // bar is a SIBLING of that ternary — it has to be, because `sticky` only
    // pins while its own container is on screen and the form's Card is not the
    // container that spans the tab. So the bar is the one Save control that
    // exists while the form does not, and the mutation-only gate it shipped
    // with (`createM/updateM/saveCfgM.isPending`) is all false during a FETCH.
    //
    // One click on that button ran buildConfig() over `form` and `slots` still
    // at their `useState({})` seeds and PUT `{slots:{}}` to /admin/nudge-config
    // — a whole-blob replace, i.e. the account's nudge config gone. The gate
    // now carries the load half, and this asserts it where it broke: on the
    // WIRE, not on the attribute.
    stallTheConfig();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(screen.getByTestId("sticky-save-bar")).toBeTruthy());

    // The form really is absent — otherwise this would be testing nothing.
    expect(screen.getByText(/Loading…/i)).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: CREATE }).filter(
        (b) => !pinnedSave(CREATE).bar.contains(b)),
    ).toEqual([]);

    expect(pinnedSave(CREATE).button).toBeDisabled();

    await user.click(pinnedSave(CREATE).button);
    expect(relayPut).not.toHaveBeenCalled();   // the config blob
    expect(relayPost).not.toHaveBeenCalled();  // the automation rule
  });

  it("wakes up once the config lands, and then both controls agree", async () => {
    // The mirror of the case above: the gate is a LOAD gate, not a permanent
    // "off", and the pin and the in-flow row open together.
    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/nudge-config")) {
        return { account_id: ACCT, config: { enabled: true }, defaults: {} };
      }
      return { rules: [] };
    });
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(pinnedSave(CREATE).button).not.toBeDisabled());
    expect(inFlowSave(CREATE)).not.toBeDisabled();
  });
});

/* ── the OTHER store the same gate has to cover ─────────────────────────── */

describe("the pinned Save bar, against the automation-rule list", () => {
  const CREATE = /Create automation/i;
  const CHANGES = /Save changes/i;

  const NUDGE_CFG = { account_id: ACCT, config: { enabled: true }, defaults: {} };
  const RULE = {
    id: 7, account_id: ACCT, name: "Nudge online", kind: "nudge_online",
    is_enabled: true, every_seconds: 60, trigger: { type: "cadence" },
    payload: {}, quiet_hours: null, created_at: null, last_run: null,
    next_due_at: null, has_pending_job: false,
  };

  /** The config lands; the RULE LIST is the thing still in flight. */
  function stallTheRuleList() {
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith("/admin/nudge-config")) return Promise.resolve(NUDGE_CFG);
      if (path.startsWith("/admin/automation-rules")) return new Promise(() => {});
      return Promise.resolve({});
    });
  }

  it("🚨 is disabled until the RULE LIST lands, and creates no second detector", async () => {
    // The config gate is not the only one this tab needs. save() branches
    // create-vs-update on `rule`, which comes from the rule LIST, and that list
    // is a different query with a different lifetime. With it still in flight
    // `rule` is null, so a click takes the CREATE branch and POSTs a second
    // nudge_online rule beside the one already there —
    // service/automation_rules_api.py enforces no (account_id, kind)
    // uniqueness, so both survive and both run the 60s detector: the fan is
    // nudged twice, and later edits reach only one of the pair.
    stallTheRuleList();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });

    // The FORM is on screen — so this case is about the rule list, not a
    // second helping of the config gate the cases above already pin.
    await waitFor(() => expect(inFlowSave(CREATE)).toBeTruthy());
    expect(screen.queryByText(/Loading…/i)).toBeNull();

    expect(pinnedSave(CREATE).button).toBeDisabled();
    expect(inFlowSave(CREATE)).toBeDisabled();

    // The wire, not the attribute.
    await user.click(pinnedSave(CREATE).button);
    expect(relayPost).not.toHaveBeenCalled();  // the duplicate rule
    expect(relayPut).not.toHaveBeenCalled();   // the config blob
  });

  it("survives a FAILED background refetch of that list — both controls stay live", async () => {
    // The mirror hazard, and the reason the gate reads `rulesQ.data !== undefined`
    // rather than `rulesQ.isSuccess`. That query polls every 30s and refetches on
    // window focus (hooks/useAutomations.ts), and a failed BACKGROUND refetch
    // moves the observer to status "error" while `data` stays exactly as it was.
    // An `isSuccess` gate reads that as "not loaded" and takes BOTH Save controls
    // away from an operator three screens into an edit — silently, since `error`
    // carries nothing — until some later poll happens to succeed.
    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/nudge-config")) return NUDGE_CFG;
      if (path.startsWith("/admin/automation-rules")) return { rules: [RULE] };
      return {};
    });
    relayPut.mockResolvedValue({ ok: true });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper: wrapperFor(qc) });

    await waitFor(() => expect(pinnedSave(CHANGES).button).not.toBeDisabled());

    // The next poll fails. Nothing else changes.
    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/nudge-config")) return NUDGE_CFG;
      if (path.startsWith("/admin/automation-rules")) throw new Error("relay down");
      return {};
    });
    await act(async () => { await qc.refetchQueries().catch(() => {}); });

    // Prove the state this case is about is really on the board: one query
    // holding BOTH an error and its data. Without this the case could pass on a
    // refetch that never happened.
    const wedged = qc.getQueryCache().getAll()
      .filter((q) => q.state.status === "error" && q.state.data !== undefined);
    expect(wedged).toHaveLength(1);

    expect(pinnedSave(CHANGES).button).not.toBeDisabled();
    expect(inFlowSave(CHANGES)).not.toBeDisabled();

    // And it still saves — the gate is open on the wire, not just in the DOM.
    await user.click(pinnedSave(CHANGES).button);
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
  });
});
