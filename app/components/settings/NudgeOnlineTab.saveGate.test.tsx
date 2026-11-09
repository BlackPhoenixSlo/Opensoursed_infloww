/**
 * NudgeOnlineTab's Save gate.
 *
 * The tab lives in the Automated editor's dialog and has ONE Save, in the dialog's footer (`EditorFooter`). Three
 * properties are worth a test, and two of them guard against writing something the operator did not ask for:
 *
 *   • The gate carries the LOAD half. A save on a FAILED or EMPTY load posts a sparse blob that REPLACES the
 *     account's stored config. The footer is drawn outside the `drafted` ternary that holds the form, so the Save
 *     is on screen at a moment when the form does not exist at all, and a gate that only watched the mutations was
 *     wide open there. Asserted on the WIRE: a `disabled` attribute that looks right while a PUT still goes out is
 *     precisely the failure that matters.
 *
 *   • That gate covers EVERY store the save writes, for the right window. The tab writes two: the config blob and
 *     an automation RULE, and the rule list is a second query with its own lifetime — with it still in flight
 *     `rule` is null, so a save creates a duplicate detector. The mirror matters as much: that list POLLS, so the
 *     gate reads `data !== undefined` and not `isSuccess`, or one failed background refetch would take the Save
 *     away mid-edit. Both directions are asserted.
 *
 *   • It fires the config PUT.
 *
 * `theSave(name)` asserts the tab has exactly ONE button by that name (no second Save in the body) and returns it.
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

/** The tab's one Save (the footer's): exactly one button answers to `name`. */
function theSave(name: RegExp): HTMLElement {
  const hit = screen.getAllByRole("button", { name });
  expect(hit).toHaveLength(1);
  return hit[0];
}

describe("the Save", () => {
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

  it("is the tab's one Save: in the footer, no second one in the body", async () => {
    loaded();
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(theSave(SAVE)).not.toBeDisabled());
  });

  it("fires the config PUT", async () => {
    loaded();
    relayPut.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(theSave(SAVE)).not.toBeDisabled());
    await user.click(theSave(SAVE));
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
    expect(String(relayPut.mock.calls.at(-1)![0])).toMatch(/^\/admin\/nudge-config/);
  });
});

describe("the Save, while the form is behind its loading branch", () => {
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
    // THE PLACEMENT CASE. NudgeOnlineTab draws its form only once the draft is
    // seeded (`drafted ? <form> : Loading…`), and the footer's Save is a
    // SIBLING of that ternary. So the Save exists while the form does not, and
    // a mutation-only gate (`saveCfgM.isPending`) is all false during a FETCH.
    //
    // One click on that button ran buildConfig() over `form` and `slots` still
    // at their `useState({})` seeds and PUT `{slots:{}}` to /admin/nudge-config
    // — a whole-blob replace, i.e. the account's nudge config gone. The gate
    // now carries the load half, and this asserts it where it broke: on the
    // WIRE, not on the attribute.
    stallTheConfig();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(theSave(CREATE)).toBeTruthy());

    // The form really is absent — otherwise this would be testing nothing.
    expect(screen.getByText(/Loading…/i)).toBeTruthy();

    expect(theSave(CREATE)).toBeDisabled();

    await user.click(theSave(CREATE));
    expect(relayPut).not.toHaveBeenCalled();   // the config blob
    expect(relayPost).not.toHaveBeenCalled();  // the automation rule
  });

  it("wakes up once the config lands", async () => {
    // The mirror of the case above: the gate is a LOAD gate, not a permanent
    // "off".
    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/nudge-config")) {
        return { account_id: ACCT, config: { enabled: true }, defaults: {} };
      }
      return { rules: [] };
    });
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(theSave(CREATE)).not.toBeDisabled());
  });
});

/* ── the OTHER store the same gate has to cover ─────────────────────────── */

describe("the Save, against the automation-rule list", () => {
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
    await waitFor(() => expect(screen.getByLabelText("Delay (min)")).toBeTruthy());
    expect(screen.queryByText(/Loading…/i)).toBeNull();

    expect(theSave(CREATE)).toBeDisabled();

    // The wire, not the attribute.
    await user.click(theSave(CREATE));
    expect(relayPost).not.toHaveBeenCalled();  // the duplicate rule
    expect(relayPut).not.toHaveBeenCalled();   // the config blob
  });

  it("survives a FAILED background refetch of that list — Save stays live", async () => {
    // The mirror hazard, and the reason the gate reads `rulesQ.data !== undefined`
    // rather than `rulesQ.isSuccess`. That query polls every 30s and refetches on
    // window focus (hooks/useAutomations.ts), and a failed BACKGROUND refetch
    // moves the observer to status "error" while `data` stays exactly as it was.
    // An `isSuccess` gate reads that as "not loaded" and takes the Save
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

    await waitFor(() => expect(theSave(CHANGES)).not.toBeDisabled());

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

    expect(theSave(CHANGES)).not.toBeDisabled();

    // And it still saves — the gate is open on the wire, not just in the DOM.
    await user.click(theSave(CHANGES));
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
  });
});
