import { describe, expect, it } from "vitest";

import { funnelStatus, startedAgo } from "@/components/automations/funnelList";

const S = (last: string | null, active_fans = 0, listening = false) => ({ last_started_at: last, active_fans, listening });

describe("funnelStatus", () => {
  it.each([
    ["no stats yet", undefined, true, null],
    ["never started", S(null), true, "Not started"],
    ["fans walking, follow-ups on", S("2026-11-11T10:00:00", 3), true, "Running"],
    ["listening for repliers, follow-ups on", S("2026-11-11T10:00:00", 0, true), true, "Running"],
    ["fans walking, follow-ups off", S("2026-11-11T10:00:00", 3), false, "Paused"],
    ["listening, follow-ups off", S("2026-11-11T10:00:00", 0, true), false, "Paused"],
    ["started, nobody left", S("2026-10-01T10:00:00"), true, "Completed"],
    ["started, nobody left, follow-ups off", S("2026-10-01T10:00:00"), false, "Completed"],
  ])("%s → %s", (_n, stats, on, label) => {
    expect(funnelStatus(stats, on)?.label ?? null).toBe(label);
  });
});

describe("startedAgo", () => {
  const now = Date.parse("2026-11-11T12:00:00Z");
  it.each([
    [null, null],
    ["garbage", null],
    ["2026-11-11T11:59:40", "just now"],
    ["2026-11-11T11:20:00", "40 min ago"],
    ["2026-11-11T09:00:00Z", "3 h ago"],
    ["2026-11-07T12:00:00+00:00", "4 d ago"],
  ])("%s → %s", (iso, want) => expect(startedAgo(iso, now)).toBe(want));
});
