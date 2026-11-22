/** The client-held bulk unsend run: one at a time, its warning tied to the run, not a component. */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { QueryClient } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, delete: vi.fn() } };
});

import { relay } from "@/lib/relay";
import { startBulkUnsend, stopBulkUnsends } from "./useBulkUnsend";
import type { ActionableRow } from "./massUnsendRules";

const relayDelete = relay.delete as unknown as Mock;
const rows = (ids: number[]): ActionableRow[] => ids.map((id) => ({ id, __accountId: "acc-a", canUnsend: true }));
const closeIsWarned = () => {
  const e = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(e);
  return e.defaultPrevented;
};

afterEach(() => relayDelete.mockReset());

describe("startBulkUnsend", () => {
  it("refuses a second run while one is going; the first sends each row once", async () => {
    const qc = new QueryClient();
    const waiting: (() => void)[] = [];
    relayDelete.mockImplementation(() => new Promise((res) => waiting.push(() => res({ success: true }))));
    const first = startBulkUnsend(qc, "all", rows([1, 2]));
    expect(closeIsWarned()).toBe(true);
    await startBulkUnsend(qc, "all", rows([3]));
    for (let i = 0; i < 2; i++) {
      await vi.waitFor(() => expect(waiting.length).toBe(1));
      waiting.shift()!();
    }
    await first;
    expect(relayDelete.mock.calls.map(([p]) => p)).toEqual(["/api/of/v2/messages/queue/1", "/api/of/v2/messages/queue/2"]);
    expect(closeIsWarned()).toBe(false);
    expect(qc.getQueryData(["bulk-unsend-run"])).toMatchObject({ running: null, note: null });
  });

  it("a cache wipe mid-run keeps the lock: a second run sends nothing, each row is deleted once", async () => {
    const qc = new QueryClient();
    const waiting: (() => void)[] = [];
    relayDelete.mockImplementation(() => new Promise((res) => waiting.push(() => res({ success: true }))));
    const first = startBulkUnsend(qc, "all", rows([1, 2]));
    await vi.waitFor(() => expect(waiting.length).toBe(1));
    qc.clear();
    const second = startBulkUnsend(qc, "all", rows([1, 2]));
    await new Promise((r) => setTimeout(r, 20));
    expect(relayDelete).toHaveBeenCalledTimes(1);
    await second;
    for (let i = 0; i < 2; i++) {
      await vi.waitFor(() => expect(waiting.length).toBe(1));
      waiting.shift()!();
    }
    await first;
    expect(relayDelete.mock.calls.map(([p]) => p)).toEqual(["/api/of/v2/messages/queue/1", "/api/of/v2/messages/queue/2"]);
    expect(closeIsWarned()).toBe(false);
  });

  it("an identity switch stops the queued deletes and drops the old run's progress and finish", async () => {
    const qc = new QueryClient();
    const waiting: (() => void)[] = [];
    relayDelete.mockImplementation(() => new Promise((res) => waiting.push(() => res({ success: false }))));
    const first = startBulkUnsend(qc, "all", rows([1, 2, 3]));
    await vi.waitFor(() => expect(waiting.length).toBe(1));
    qc.clear();
    stopBulkUnsends();
    waiting.shift()!();
    await first;
    expect(relayDelete).toHaveBeenCalledTimes(1);
    expect(qc.getQueryData(["bulk-unsend-run"])).toBeUndefined();
    expect(closeIsWarned()).toBe(false);
    relayDelete.mockResolvedValue({ success: true });
    await startBulkUnsend(qc, "all", rows([4]));
    expect(relayDelete.mock.calls.map(([p]) => p)).toEqual(["/api/of/v2/messages/queue/1", "/api/of/v2/messages/queue/4"]);
  });
});
