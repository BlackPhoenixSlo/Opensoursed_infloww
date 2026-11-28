import { afterEach, describe, expect, it, vi } from "vitest";

import type { AppliedSettings } from "@/lib/appliedSettings";

const q = vi.hoisted(() => ({ value: { isPending: false, data: undefined } as { isPending: boolean; data?: Partial<AppliedSettings> } }));
vi.mock("@/lib/appliedSettings", () => ({ useAppliedSettings: () => q.value }));

import { useFlags } from "./useFlags";

afterEach(() => vi.unstubAllEnvs());

describe("useFlags", () => {
  it.each([
    ["pending", { isPending: true }, undefined, undefined],
    ["no data: server defaults", { isPending: false }, undefined, { fansly_manager: true, leak_tracker: false }],
    ["stored off", { isPending: false, data: { flags: { fansly_manager: false, leak_tracker: false } } }, undefined, { fansly_manager: false, leak_tracker: false }],
    ["no mirror in the build", { isPending: false }, "1", { fansly_manager: false, leak_tracker: false }],
    ["no mirror keeps other flags", { isPending: false, data: { flags: { fansly_manager: true, leak_tracker: true } } }, "1", { fansly_manager: false, leak_tracker: true }],
    ["mirror present", { isPending: false, data: { flags: { fansly_manager: true, leak_tracker: false } } }, "", { fansly_manager: true, leak_tracker: false }],
  ])("%s", (_, value, absent, want) => {
    q.value = value;
    if (absent !== undefined) vi.stubEnv("NEXT_PUBLIC_FANSLY_MIRROR_ABSENT", absent);
    expect(useFlags()).toEqual(want);
  });
});
