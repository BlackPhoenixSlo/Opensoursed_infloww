import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

import type { AccountMeta } from "@/lib/relay";

const h = vi.hoisted(() => ({
  platformAccounts: [] as AccountMeta[],
  scope: { kind: "all" } as { kind: "all" } | { kind: "model"; accountId: string },
}));
vi.mock("@/hooks/useAccounts", () => ({ usePlatformAccounts: () => h.platformAccounts }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ scope: h.scope }) }));
vi.mock("@/hooks/useAllModelsInclude", () => ({ useAllModelsInclude: () => ({ isIncluded: () => true }) }));

import { AccountPicker } from "./AccountPicker";
import { massSenders } from "./massSenders";

const acct = (id: string, platform?: string): AccountMeta =>
  ({ id, nickname: id, platform, is_active: true, has_session: true }) as AccountMeta;
const of1 = acct("of1", "onlyfans");
const of2 = acct("of2", "onlyfans");
const fs1 = acct("fs1", "fansly");

afterEach(cleanup);

describe("AccountPicker auto-seed", () => {
  it.each<[string, AccountMeta[], typeof h.scope, "mass" | "post", string | null]>([
    ["scoped OnlyFans Creator in the list seeds herself", [of1, of2], { kind: "model", accountId: "of2" }, "mass", "of2"],
    ["scoped OnlyFans Creator with an expired session still seeds herself", [of1], { kind: "model", accountId: "ofX" }, "mass", "ofX"],
    ["scoped Fansly Creator in the mass composer seeds herself; validation refuses her", [fs1], { kind: "model", accountId: "fs1" }, "mass", "fs1"],
    ["scoped Fansly Creator in Post seeds herself", [fs1], { kind: "model", accountId: "fs1" }, "post", "fs1"],
    ["All Models seeds the first sender", [of1, of2], { kind: "all" }, "mass", "of1"],
    ["All Models in Fansly mode seeds none for a mass message", [fs1], { kind: "all" }, "mass", null],
  ])("%s", (_label, platformAccounts, scope, composer, want) => {
    h.platformAccounts = platformAccounts;
    h.scope = scope;
    const platform = platformAccounts[0]?.platform === "fansly" ? "fansly" : "onlyfans";
    const accounts = composer === "mass" ? massSenders(platformAccounts, platform) : undefined;
    const onChange = vi.fn();
    render(<AccountPicker value={null} onChange={onChange} accounts={accounts} />);
    if (want) expect(onChange).toHaveBeenCalledWith(want);
    else expect(onChange).not.toHaveBeenCalled();
  });
});
