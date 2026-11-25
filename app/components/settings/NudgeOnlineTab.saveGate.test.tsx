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

function wrapperFor(qc: QueryClient) {
  return function Bound({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

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

  function stallTheConfig() {
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith("/admin/nudge-config")) return new Promise(() => {});
      return Promise.resolve({ rules: [] });
    });
  }

  it("🚨 is on screen DURING the fetch, disabled, and sends NOTHING", async () => {
    stallTheConfig();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(theSave(CREATE)).toBeTruthy());

    expect(screen.getByText(/Loading…/i)).toBeTruthy();

    expect(theSave(CREATE)).toBeDisabled();

    await user.click(theSave(CREATE));
    expect(relayPut).not.toHaveBeenCalled();
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("wakes up once the config lands", async () => {
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

  function stallTheRuleList() {
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith("/admin/nudge-config")) return Promise.resolve(NUDGE_CFG);
      if (path.startsWith("/admin/automation-rules")) return new Promise(() => {});
      return Promise.resolve({});
    });
  }

  it("🚨 is disabled until the RULE LIST lands, and creates no second detector", async () => {
    stallTheRuleList();
    const user = userEvent.setup();
    render(<NudgeOnlineTab />, { wrapper });

    await waitFor(() => expect(screen.getByLabelText("Delay (min)")).toBeTruthy());
    expect(screen.queryByText(/Loading…/i)).toBeNull();

    expect(theSave(CREATE)).toBeDisabled();

    await user.click(theSave(CREATE));
    expect(relayPost).not.toHaveBeenCalled();
    expect(relayPut).not.toHaveBeenCalled();
  });

  it("survives a FAILED background refetch of that list — Save stays live", async () => {
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

    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/nudge-config")) return NUDGE_CFG;
      if (path.startsWith("/admin/automation-rules")) throw new Error("relay down");
      return {};
    });
    await act(async () => { await qc.refetchQueries().catch(() => {}); });

    const wedged = qc.getQueryCache().getAll()
      .filter((q) => q.state.status === "error" && q.state.data !== undefined);
    expect(wedged).toHaveLength(1);

    expect(theSave(CHANGES)).not.toBeDisabled();

    await user.click(theSave(CHANGES));
    await waitFor(() => expect(relayPut).toHaveBeenCalled());
  });
});
