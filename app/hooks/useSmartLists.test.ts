/**
 * resolveSmartLists — the mass composer's picked Smart Lists as fan ids at send
 * time: one /resolve per list, de-duped across lists, and no call at all for an
 * empty pick (an empty include must not look like "everyone").
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));
vi.mock("@/lib/relay", () => ({ relay: { get: (path: string) => getSpy(path) } }));

import { resolveSmartLists } from "@/hooks/useSmartLists";

const RESOLVE_MAP: Record<string, number[]> = {
  "/admin/smart-lists/1/resolve": [10, 11, 12],
  "/admin/smart-lists/2/resolve": [12, 13],
};

afterEach(() => getSpy.mockReset());

describe("resolveSmartLists", () => {
  it("resolves each list once and de-dupes across them", async () => {
    getSpy.mockImplementation(async (path: string) => ({ fan_ids: RESOLVE_MAP[path] ?? [] }));
    expect(await resolveSmartLists(new Set([1, 2]))).toEqual([10, 11, 12, 13]);
    expect(getSpy.mock.calls.map(([p]) => p).sort()).toEqual(Object.keys(RESOLVE_MAP));
  });

  it("short-circuits the empty set", async () => {
    expect(await resolveSmartLists(new Set())).toEqual([]);
    expect(getSpy).not.toHaveBeenCalled();
  });
});
