import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { FanId } from "@/lib/fanId";

const OF_FAN: FanId = 582413509;
const FANSLY_FAN: FanId = "900604711209099264";

// react-query hashes 12345 and "12345" to different keys: invalidate with the structured fan id, never one rebuilt from a string key.
function invalidateLikeTheRail(qc: QueryClient, aid: string, fanId: FanId) {
  void qc.invalidateQueries({ queryKey: ["chat-detail", aid, fanId] });
  void qc.invalidateQueries({ queryKey: ["money-rail-attrib", aid, fanId] });
}

function seeded(fanId: FanId) {
  const qc = new QueryClient();
  qc.setQueryData(["chat-detail", "acct", fanId], { ok: true });
  qc.setQueryData(["money-rail-attrib", "acct", fanId], { ok: true });
  return qc;
}

const isInvalidated = (qc: QueryClient, key: unknown[]) =>
  qc.getQueryCache().find({ queryKey: key })?.state.isInvalidated ?? false;

describe("MoneyRail stale-detail invalidation", () => {
  it("invalidates a numeric OnlyFans id", () => {
    const qc = seeded(OF_FAN);
    invalidateLikeTheRail(qc, "acct", OF_FAN);
    expect(isInvalidated(qc, ["chat-detail", "acct", OF_FAN])).toBe(true);
    expect(isInvalidated(qc, ["money-rail-attrib", "acct", OF_FAN])).toBe(true);
  });

  it("invalidates a Fansly string snowflake", () => {
    const qc = seeded(FANSLY_FAN);
    invalidateLikeTheRail(qc, "acct", FANSLY_FAN);
    expect(isInvalidated(qc, ["chat-detail", "acct", FANSLY_FAN])).toBe(true);
    expect(isInvalidated(qc, ["money-rail-attrib", "acct", FANSLY_FAN])).toBe(true);
  });

  it("proves WHY the string round trip broke each platform in turn", () => {
    const ofQc = seeded(OF_FAN);
    invalidateLikeTheRail(ofQc, "acct", String(OF_FAN) as FanId);
    expect(isInvalidated(ofQc, ["chat-detail", "acct", OF_FAN])).toBe(false);

    const fanslyQc = seeded(FANSLY_FAN);
    invalidateLikeTheRail(fanslyQc, "acct", Number(FANSLY_FAN) as FanId);
    expect(isInvalidated(fanslyQc, ["chat-detail", "acct", FANSLY_FAN])).toBe(false);
  });
});
