import { describe, it, expect } from "vitest";
import { needsKey } from "./AgencyKeyBadges";

describe("needsKey", () => {
  const base = {
    accounts: 1, live_accounts: 0, blocked_accounts: 0,
    providers_set: [] as string[], missing_providers: [] as string[],
  };

  it("fires on a live model with no key", () => {
    expect(needsKey({ ...base, live_accounts: 1, missing_providers: ["deepseek"] })).toBe(true);
  });

  it("stays quiet when the required key is stored", () => {
    expect(needsKey({ ...base, live_accounts: 1, providers_set: ["deepseek"] })).toBe(false);
  });

  it("FIRES on the wrong provider's key — credentials resolve per provider", () => {
    expect(needsKey({
      ...base, live_accounts: 1,
      providers_set: ["deepinfra"], missing_providers: ["deepseek"],
    })).toBe(true);
  });

  it("falls back to has-no-key when the backend predates missing_providers", () => {
    const legacy = { accounts: 1, live_accounts: 1, blocked_accounts: 0, providers_set: [] };
    expect(needsKey(legacy)).toBe(true);
    expect(needsKey({ ...legacy, providers_set: ["deepseek"] })).toBe(false);
  });

  it("stays quiet when nothing can talk — a key would buy nothing yet", () => {
    expect(needsKey({ ...base, accounts: 5, live_accounts: 0, missing_providers: ["deepseek"] })).toBe(false);
  });

  it("stays quiet for an agency whose only live models are BLOCKED", () => {
    expect(needsKey({ ...base, live_accounts: 0, blocked_accounts: 2, missing_providers: ["deepseek"] })).toBe(false);
  });
});
