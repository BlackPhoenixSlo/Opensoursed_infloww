import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: { user_id: 1 } }),
}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn() } };
});

import { OfmWritesCard } from "@/components/settings/OfmWritesTab";
import { ofmWritesStatus, type OfmWritesCreator } from "@/hooks/useOfmWritesCreator";
import { OFM_WRITES_KEY, OFM_WRITES_PATH, relaySwitchQuery } from "@/lib/ofMirrorNewWrites";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;

const view = (over: Partial<OfmWritesCreator>): OfmWritesCreator => ({
  account_id: "9", server_on: true, forced_off: false, on: true, changed_by: null, changed_at: null, ...over,
});

function mount(state: OfmWritesCreator) {
  let cur = state;
  relayGet.mockImplementation(async () => cur);
  relayPut.mockImplementation(async (_p: string, body: { forced_off: boolean }) => {
    cur = { ...cur, forced_off: body.forced_off, on: cur.server_on && !body.forced_off,
      changed_by: body.forced_off ? "boss" : null, changed_at: body.forced_off ? "2026-11-21T10:00:00Z" : null };
    return cur;
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>);
  render(<OfmWritesCard accountId="9" />, { wrapper: wrap });
  return { invalidate };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("ofmWritesStatus", () => {
  it.each([
    [{ server_on: false, forced_off: false }, "Off for every creator on this server. This switch can only keep it off here."],
    [{ server_on: false, forced_off: true }, "Off for every creator on this server. This switch can only keep it off here."],
    [{ server_on: true, forced_off: true }, "Off for this creator."],
    [{ server_on: true, forced_off: false }, "On for this creator."],
  ])("%j -> %s", (v, want) => expect(ofmWritesStatus(v)).toBe(want));
});

describe("OfmWritesCard", () => {
  it("one click forces it off, names who and when, and re-asks the Mirror's probe", async () => {
    const { invalidate } = mount(view({}));
    const box = await screen.findByRole("checkbox", { name: "Keep OF Manager new writes off for this creator" });
    expect(box).not.toBeChecked();
    expect(screen.getByTestId("ofm-writes-status").textContent).toBe("On for this creator.");
    expect(screen.queryByTestId("ofm-writes-who")).toBeNull();
    fireEvent.click(box);
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/ofm-writes/9", { forced_off: true }));
    await waitFor(() => expect(box).toBeChecked());
    expect(screen.getByTestId("ofm-writes-status").textContent).toBe("Off for this creator.");
    expect(screen.getByTestId("ofm-writes-who").textContent).toMatch(/^Turned off by boss · /);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [OFM_WRITES_KEY] });
  });

  it("server off: unticked still reads off (clearing never turns it on)", async () => {
    mount(view({ server_on: false, on: false, forced_off: true, changed_by: "boss", changed_at: "2026-11-21T10:00:00Z" }));
    const box = await screen.findByTestId("ofm-writes-box");
    fireEvent.click(box);
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/ofm-writes/9", { forced_off: false }));
    await waitFor(() => expect(box).not.toBeChecked());
    expect(screen.getByTestId("ofm-writes-status").textContent).toMatch(/^Off for every creator/);
  });
});

describe("relaySwitchQuery (the Mirror's probes)", () => {
  it("a per-Creator probe is keyed by and sent for its Creator", async () => {
    relayGet.mockResolvedValue({ on: true });
    const q = relaySwitchQuery(OFM_WRITES_KEY, OFM_WRITES_PATH, "on", "42");
    expect(q.queryKey).toEqual([OFM_WRITES_KEY, "42"]);
    expect(await q.queryFn()).toBe(true);
    expect(relayGet).toHaveBeenCalledWith(OFM_WRITES_PATH, { accountId: "42" });
    expect(q.refetchInterval).toBe(60_000);
  });

  it("a box-wide probe (Go live) keeps its one key and sends no Creator", async () => {
    relayGet.mockRejectedValue(new Error("404"));
    const q = relaySwitchQuery("of-live-window", "/api/of/live-window", "enabled");
    expect(q.queryKey).toEqual(["of-live-window"]);
    expect(await q.queryFn()).toBe(false);
    expect(relayGet).toHaveBeenCalledWith("/api/of/live-window", undefined);
    expect(q.refetchInterval).toBe(false);
  });
});
