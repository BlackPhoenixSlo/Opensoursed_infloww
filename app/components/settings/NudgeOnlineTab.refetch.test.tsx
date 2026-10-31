/**
 * NudgeOnlineTab over a config REFETCH (save / roll-out invalidation, remount)
 * and over its own save: the draft an operator is editing must survive a
 * refetch; an untouched form takes the server's new values; a save that lands
 * after an account switch refreshes the account it wrote. Drives the real
 * component + react-query; only the relay wire and the account list are faked
 * (as in stickySave.test.tsx).
 */
import { afterEach, beforeAll, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, notifyManager } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn() },
  };
});

const A = "123456789";
const B = "223456789";
const acc = vi.hoisted(() => ({ list: [] as { id: string; nickname: string; has_session: boolean }[] }));
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return { ...mod, useActiveAccounts: () => acc.list };
});

import NudgeOnlineTab from "@/components/settings/NudgeOnlineTab";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;

type Server = Record<string, { delay_minutes: number; jitter_minutes?: number }>;

/** Serves `/admin/nudge-config` with whatever `server[account]` holds now;
 *  returns the handler, for a test that wraps it. Answers on a later task, as
 *  a real read does: a refetch a save's onSettled starts cannot land in the
 *  microtasks before save() dispatches `saveOk` (the reducer relies on it). */
function serve(server: Server) {
  const get = async (path: string) => {
    await new Promise((r) => setTimeout(r, 0));
    if (path.startsWith("/admin/nudge-config")) {
      const id = new URLSearchParams(path.split("?")[1]).get("account_id")!;
      return { account_id: id, config: { ...server[id] }, defaults: {} };
    }
    if (path.startsWith("/admin/automation-rules")) return { rules: [] };
    return {};
  };
  relayGet.mockImplementation(get);
  return get;
}

/** The next PUT waits for `release()`, then stores its config. */
function holdPut(server: Server) {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  relayPut.mockImplementationOnce(async (_path: string, body: { account_id: string; config: Server[string] }) => {
    await gate;
    server[body.account_id] = body.config;
    return body;
  });
  return () => act(async () => { release(); });
}

function mount(ids = [A]) {
  acc.list = ids.map((id) => ({ id, nickname: `acct-${id}`, has_session: true }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NudgeOnlineTab />
    </QueryClientProvider>,
  );
  return qc;
}
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const delay = () => field("Delay (min)");
const jitter = () => field("Jitter (min)");
const saveButton = () => screen.getAllByRole("button", { name: "Create automation" })[0];
const cfgState = (qc: QueryClient, id: string) => qc.getQueryState(["nudge-config", id]);
/** First load (config + rule list); slow under the full suite's load. */
const ready = () => waitFor(() => expect(saveButton()).not.toBeDisabled(), { timeout: 5_000 });

// react-query notifies on a setTimeout by default; synchronous here, so an
// awaited `act` has also run the hydrate effect (no fixed waits).
beforeAll(() => { notifyManager.setScheduler((cb) => cb()); });
// reset, not clear: a test that fails before its PUT must not leave its
// `mockImplementationOnce` queued for the next test's PUT.
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("NudgeOnlineTab over a config refetch", () => {
  it("keeps an unsaved edit when the config refetches", async () => {
    const server: Server = { [A]: { delay_minutes: 4 } };
    serve(server);
    const qc = mount();
    await waitFor(() => expect(delay().value).toBe("4"));

    fireEvent.change(delay(), { target: { value: "9" } });
    expect(delay().value).toBe("9");

    server[A] = { delay_minutes: 6 };
    await act(async () => { await qc.refetchQueries({ queryKey: ["nudge-config"] }); });
    expect(cfgState(qc, A)?.dataUpdateCount).toBe(2);
    expect(delay().value).toBe("9");
  });

  it("an untouched form takes the refetched values", async () => {
    const server: Server = { [A]: { delay_minutes: 4 } };
    serve(server);
    const qc = mount();
    await waitFor(() => expect(delay().value).toBe("4"));

    server[A] = { delay_minutes: 6 };
    await act(async () => { await qc.refetchQueries({ queryKey: ["nudge-config"] }); });
    expect(delay().value).toBe("6");
  });
});

describe("NudgeOnlineTab over its own save", () => {
  it("an edit typed while the save is in flight survives the save's refetch", async () => {
    const server: Server = { [A]: { delay_minutes: 4, jitter_minutes: 3 } };
    serve(server);
    const release = holdPut(server);
    const qc = mount();
    await ready();

    fireEvent.change(delay(), { target: { value: "9" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    fireEvent.change(jitter(), { target: { value: "1" } });

    await release();
    await waitFor(() => expect(cfgState(qc, A)?.dataUpdateCount).toBe(2));
    await act(async () => {});
    expect([delay().value, jitter().value]).toEqual(["9", "1"]);
  });

  it("an account switch mid-save refreshes the saving account, not the shown one", async () => {
    const server: Server = { [A]: { delay_minutes: 4 }, [B]: { delay_minutes: 1 } };
    serve(server);
    const release = holdPut(server);
    const qc = mount([A, B]);
    await ready();

    fireEvent.change(delay(), { target: { value: "9" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    const picker = screen.getByDisplayValue(`acct-${A}`);
    fireEvent.change(picker, { target: { value: B } });
    await waitFor(() => expect(delay().value).toBe("1"));

    await release();
    await waitFor(() => expect(cfgState(qc, A)?.isInvalidated).toBe(true));
    expect(screen.queryByText("✓ Saved.")).toBeNull();
    expect(screen.queryByText("Saved ✓")).toBeNull();

    fireEvent.change(picker, { target: { value: A } });
    await waitFor(() => expect(delay().value).toBe("9"));
  });

  it("A's save in flight is not B's: B's Save is live, not 'Saving…'", async () => {
    const server: Server = { [A]: { delay_minutes: 4 }, [B]: { delay_minutes: 1 } };
    serve(server);
    const release = holdPut(server);
    mount([A, B]);
    await ready();

    fireEvent.click(saveButton());
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Saving/ }).length).toBeGreaterThan(0));
    fireEvent.change(screen.getByDisplayValue(`acct-${A}`), { target: { value: B } });
    await waitFor(() => expect(delay().value).toBe("1"));
    expect(screen.queryAllByRole("button", { name: /Saving/ })).toEqual([]);
    await waitFor(() => expect(saveButton()).not.toBeDisabled());
    await release();
  });

  it("back on A mid-save, A's Save stays off until its PUT settles (no second PUT)", async () => {
    const server: Server = { [A]: { delay_minutes: 4 }, [B]: { delay_minutes: 1 } };
    serve(server);
    const release = holdPut(server);
    mount([A, B]);
    await ready();

    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    const picker = screen.getByDisplayValue(`acct-${A}`);
    fireEvent.change(picker, { target: { value: B } });
    await waitFor(() => expect(delay().value).toBe("1"));
    fireEvent.change(picker, { target: { value: A } });
    // A's form waits for a config from after the save (the cache holds the pre-PUT one).
    const saving = () => screen.getAllByRole("button", { name: /Saving/ });
    await waitFor(() => expect(saving().length).toBeGreaterThan(0));
    expect(screen.queryByLabelText("Delay (min)")).toBeNull();
    saving().forEach((b) => expect(b).toBeDisabled());
    fireEvent.click(saving()[0]);
    expect(relayPut).toHaveBeenCalledTimes(1);

    await release();
    await waitFor(() => expect(saveButton()).not.toBeDisabled());
    expect(delay().value).toBe("4");
    expect(relayPut).toHaveBeenCalledTimes(1);
  });

  it("A's failed save shows on A after A → B → A mid-save", async () => {
    const server: Server = { [A]: { delay_minutes: 4 }, [B]: { delay_minutes: 1 } };
    serve(server);
    let reject!: (e: Error) => void;
    relayPut.mockImplementationOnce(() => new Promise((_r, j) => { reject = j; }));
    mount([A, B]);
    await ready();

    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    const picker = screen.getByDisplayValue(`acct-${A}`);
    fireEvent.change(picker, { target: { value: B } });
    await waitFor(() => expect(delay().value).toBe("1"));
    fireEvent.change(picker, { target: { value: A } });
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Saving/ }).length).toBeGreaterThan(0));
    await act(async () => { reject(new Error("PUT boom")); });
    await waitFor(() => expect(screen.getAllByText("PUT boom").length).toBeGreaterThan(0));
    // The failed save refreshes A too (onSettled), so the form is seeded again.
    await waitFor(() => expect(delay().value).toBe("4"));
    await waitFor(() => expect(saveButton()).not.toBeDisabled());
  });

  it("A → B → A mid-save: A's form waits for the post-PUT refetch; the next Save keeps PUT1's fields", async () => {
    const server: Server = { [A]: { delay_minutes: 6, jitter_minutes: 3 }, [B]: { delay_minutes: 1 } };
    const get = serve(server);
    const release = holdPut(server);
    mount([A, B]);
    await ready();

    fireEvent.change(delay(), { target: { value: "9" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    const picker = screen.getByDisplayValue(`acct-${A}`);
    fireEvent.change(picker, { target: { value: B } });
    await waitFor(() => expect(delay().value).toBe("1"));
    // A's refetch after the PUT is held, so the window between the PUT settling and it landing is visible.
    let landGet!: () => void;
    const getGate = new Promise<void>((r) => { landGet = r; });
    const aGets: string[] = [];
    relayGet.mockImplementation(async (path: string) => {
      if (path.startsWith(`/admin/nudge-config?account_id=${A}`)) { aGets.push(path); await getGate; }
      return get(path);
    });
    fireEvent.change(picker, { target: { value: A } });
    await act(async () => {});
    // Pre-fix: Delay showed A's pre-PUT 6 here, and stayed 6 under any edit made before the refetch.
    expect(screen.queryByLabelText("Delay (min)")).toBeNull();

    await release();
    await waitFor(() => expect(aGets.length).toBe(1));
    expect(screen.queryByLabelText("Delay (min)")).toBeNull();
    expect(saveButton()).toBeDisabled();

    await act(async () => { landGet(); });
    await waitFor(() => expect(delay().value).toBe("9"));
    expect(jitter().value).toBe("3");
    fireEvent.change(jitter(), { target: { value: "1" } });
    relayPut.mockImplementationOnce(async (_p: string, body: unknown) => body);
    await waitFor(() => expect(saveButton()).not.toBeDisabled());
    fireEvent.click(saveButton());
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(2));
    expect(relayPut.mock.calls[1][1]).toMatchObject({ account_id: A, config: { delay_minutes: 9, jitter_minutes: 1 } });
  });

  it("A's 'Saved' does not stand under B when B's config fails to load", async () => {
    const server: Server = { [A]: { delay_minutes: 4 } };
    const get = serve(server);
    relayGet.mockImplementation(async (path: string) => {
      if (path.includes(`account_id=${B}`)) throw new Error("B down");
      return get(path);
    });
    relayPut.mockImplementationOnce(async (_p: string, body: unknown) => body);
    mount([A, B]);
    await ready();

    fireEvent.click(saveButton());
    await waitFor(() => expect(screen.getByText("✓ Saved.")).toBeTruthy());
    fireEvent.change(screen.getByDisplayValue(`acct-${A}`), { target: { value: B } });
    // Said where the form would be (not "Loading…" forever) and on the pinned bar.
    await waitFor(() => expect(screen.getAllByText(/Couldn't load this account's nudge settings/)).toHaveLength(2));
    expect(screen.queryByText("Loading…")).toBeNull();
    expect(screen.queryByText("✓ Saved.")).toBeNull();
    expect(screen.queryByText("Saved ✓")).toBeNull();
  });
});
