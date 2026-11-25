import { describe, expect, it } from "vitest";

import { runStatsChunks, welcomeStatsChunks } from "./runStats";

function line(stats: Record<string, unknown> | null): string {
  return runStatsChunks(stats).map((c) => c.text).join(" · ");
}

function gated(stats: Record<string, unknown>): Record<string, unknown> {
  return { no_price_skipped: 0, ...stats };
}

describe("runStatsChunks — dry-run reporting", () => {
  it("leads with what the run WOULD do, not how big the pool was", () => {
    const s = line({
      action: "follow", dry_run: true, candidates: 8, examined: 8,
      would_follow: [], already_following: 8,
      paid_profile_skipped: 0, no_price_skipped: 0, errors: 0, cap: 50,
    });
    expect(s).toContain("0 would notify");
    expect(s).toContain("8 already followed");
  });

  it("flags a zero forecast so it cannot be skimmed past", () => {
    const chunks = runStatsChunks(gated({ would_follow: [], candidates: 8, examined: 8 }));
    expect(chunks.find((c) => c.text === "0 would notify")?.tone).toBe("warn");
  });

  it("does not flag a forecast that will actually act", () => {
    const chunks = runStatsChunks(gated({ would_ping: [1, 2, 3], candidates: 40, examined: 40 }));
    const w = chunks.find((c) => c.text === "3 would notify");
    expect(w).toBeDefined();
    expect(w?.tone).toBeUndefined();
  });

  it("reads would_ping as well as would_follow", () => {
    expect(line(gated({ would_ping: [7001, 7002], examined: 2 })))
      .toContain("2 would notify");
  });

  it("says when only part of the pool was checked", () => {
    expect(line({ candidates: 250, examined: 50 }))
      .toContain("50 of 250 candidates checked");
    expect(line({ candidates: 8, examined: 8 })).toContain("8 candidates");
  });

  it("still reports a live run's real counters", () => {
    const s = line({
      action: "ping", dry_run: false, pinged: 12, stranded: 0,
      paid_profile_skipped: 3, no_price_skipped: 2, candidates: 148,
    });
    expect(s).toContain("pinged 12");
    expect(s).toContain("3 paid profiles skipped");
    expect(s).toContain("2 price unreadable, skipped");
  });

  it("is silent on an empty bag", () => {
    expect(runStatsChunks(null)).toEqual([]);
    expect(runStatsChunks({})).toEqual([]);
  });
  it("says nothing about a forecast an older relay did not gate", () => {
    const s = line({ dry_run: true, candidates: 8, would_follow: [1, 2, 3, 4, 5, 6, 7, 8] });
    expect(s).not.toContain("would notify");
    expect(s).toContain("8 candidates");
  });
});

describe("runStatsChunks — an UNGATED run, which spends real money", () => {
  it("leads with the charge, in the loudest tone, naming the count", () => {
    const chunks = runStatsChunks({
      action: "follow", dry_run: true, money_gate: false,
      would_follow: [1, 2, 3, 4, 5, 6, 7, 8], unpriced_follows: 8,
      candidates: 8, examined: 8, cap: 50,
    });
    expect(chunks[0]?.text).toBe("money gate OFF — 8 follows will be charged");
    expect(chunks[0]?.tone).toBe("err");
    expect(chunks.map((c) => c.text)).toContain("8 would notify");
  });

  it("still says the charge is coming when it cannot count it", () => {
    const chunks = runStatsChunks({ action: "follow", money_gate: false });
    expect(chunks[0]?.text).toBe("money gate OFF — paid profiles WILL be charged");
    expect(chunks[0]?.tone).toBe("err");
  });
});

describe("runStatsChunks — a tick that threw", () => {
  it("NEVER lets a failed follow tick read as a quiet day", () => {
    const chunks = runStatsChunks({
      action: "follow", dry_run: false, source: "all_stored",
      candidates: 20, followed: 0, already_following: 8, errors: 12, cap: 30,
    });
    expect(chunks[0]?.text).toBe("12 failed");
    expect(chunks[0]?.tone).toBe("err");
  });

  it("covers promo_reactivate, the other kind this formatter renders", () => {
    const chunks = runStatsChunks({ reactivated: 0, errors: 3, deferred: 1, dry_run: false });
    expect(chunks[0]?.text).toBe("3 failed");
    expect(chunks[0]?.tone).toBe("err");
  });

  it("outranks even the money-gate chunk", () => {
    const chunks = runStatsChunks({
      action: "follow", money_gate: false, followed: 2, errors: 5,
    });
    expect(chunks.map((c) => c.text).slice(0, 2)).toEqual([
      "5 failed", "money gate OFF — 2 follows will be charged",
    ]);
    expect(chunks.slice(0, 2).every((c) => c.tone === "err")).toBe(true);
  });

  it("says nothing on a clean tick", () => {
    expect(line({ action: "follow", followed: 3, errors: 0 })).not.toContain("failed");
  });
});

describe("runStatsChunks — a live run that notified nobody", () => {
  it("names the pinned window instead of letting it read as a quiet day", () => {
    const s = line({
      action: "follow", dry_run: false, candidates: 15, followed: 0,
      already_following: 15, pool_exhausted: true, errors: 0, cap: 3,
    });
    expect(s).toContain("nobody new to notify in this batch");
    expect(runStatsChunks({ pool_exhausted: true })[0]?.tone).toBe("warn");
  });

  it("stays quiet on a run that did notify someone", () => {
    const s = line({
      action: "follow", dry_run: false, candidates: 15, followed: 3,
      already_following: 12, pool_exhausted: false, errors: 0, cap: 3,
    });
    expect(s).not.toContain("nobody new to notify");
    expect(line({ action: "follow", followed: 3 })).not.toContain("nobody new to notify");
  });

  it("does not claim the table is finished while it also reports fans left", () => {
    const s = line({
      action: "follow", dry_run: false, source: "all_stored", candidates: 25,
      followed: 0, already_following: 25, pool_exhausted: true, eligible: 200,
      errors: 0, cap: 5,
    });
    expect(s).toContain("nobody new to notify in this batch");
    expect(s).toContain("200 eligible still to walk");
    expect(s).not.toContain("whole pool");
    expect(s).not.toMatch(/pool checked|nothing left|finished/i);
  });
});

describe("welcomeStatsChunks — the send_welcome follow-back lane", () => {
  const lane = (extra: Record<string, unknown> = {}) => ({
    welcomes_sent: 2, follow_back: true, follow_back_gate: true,
    followed_back: 2, follow_back_already: 0, follow_back_paid_skipped: 0,
    follow_back_no_price: 0, follow_back_errors: 0, ...extra,
  });
  const laneChunks = (stats: Record<string, unknown>) =>
    welcomeStatsChunks(stats).filter((c) => /follow|charged/.test(c.text));
  const laneLine = (stats: Record<string, unknown>) =>
    welcomeStatsChunks(stats).map((c) => c.text).join(" · ");

  it("reports what the lane did", () => {
    const s = laneLine(lane({
      followed_back: 1, follow_back_already: 1, follow_back_paid_skipped: 3,
      follow_back_no_price: 2, follow_back_errors: 1,
    }));
    expect(s).toContain("followed back 1");
    expect(s).toContain("1 already followed back");
    expect(s).toContain("3 paid subs not followed back");
    expect(s).toContain("2 follow-back prices unreadable");
    expect(s).toContain("1 follow-backs failed");
  });

  it("leads with the charge when the price-check is off", () => {
    const chunks = laneChunks(lane({ follow_back_gate: false, followed_back: 4 }));
    expect(chunks[0]?.text).toBe("follow-back gate OFF — 4 follow-backs charged blind");
    expect(chunks[0]?.tone).toBe("err");
  });

  it("says the charge is coming even on a tick that followed nobody", () => {
    const chunks = laneChunks(lane({ follow_back_gate: false, followed_back: 0 }));
    expect(chunks[0]?.text).toBe("follow-back gate OFF — paid subscribers WILL be charged");
    expect(chunks[0]?.tone).toBe("err");
  });

  it("flags a tick that welcomed people and followed nobody back", () => {
    const chunks = laneChunks(lane({ followed_back: 0, follow_back_already: 2 }));
    expect(chunks.find((c) => c.text === "followed back 0")?.tone).toBe("warn");
    expect(chunks.find((c) => c.text === "followed back 2")).toBeUndefined();
  });

  it("says nothing at all when the lane is switched off", () => {
    expect(laneLine(lane({ follow_back: false, followed_back: 0 }))).not.toContain("followed back");
  });

  it("says nothing when the run did not vouch for the knob", () => {
    const s = laneLine({ welcomes_sent: 2, followed_back: 0, follow_back_paid_skipped: 0 });
    expect(s).not.toContain("followed back");
  });

  it("stays quiet on a tick that welcomed nobody", () => {
    expect(laneChunks(lane({ welcomes_sent: 0, followed_back: 0 }))).toEqual([]);
    expect(laneLine(lane({ welcomes_sent: 0, followed_back: 0 }))).toContain("welcomed 0");
  });

  it("does not assert a charge on a run that cannot spend a cent", () => {
    const all = welcomeStatsChunks(
      lane({ dry_run: true, follow_back_gate: false, followed_back: 0 }));
    expect(all.map((c) => c.text).join(" · ")).not.toContain("WILL be charged");
    expect(all.map((c) => c.text).join(" · ")).not.toContain("charged blind");
    expect(all.some((c) => c.tone === "err")).toBe(false);
    expect(laneChunks(lane({ dry_run: true, follow_back_gate: false, followed_back: 0 }))[0]?.text)
      .toBe("follow-back gate off — a live run would follow blind");
  });

  it("does not report counters a dry run never measured", () => {
    const s = laneLine(lane({ dry_run: true, followed_back: 0 }));
    expect(s).not.toContain("followed back 0");
    expect(s).toContain("follow-back would run (dry)");
  });
  it("the GROWTH formatter says nothing about this lane at all", () => {
    expect(runStatsChunks(lane({ follow_back_gate: false, followed_back: 4 })))
      .toEqual([]);
  });
});

describe("welcomeStatsChunks — the welcome card's OWN last-run line", () => {
  const wl = (extra: Record<string, unknown> = {}) => ({
    subscribers_seen: 12, new_subscribers: 5, welcomes_sent: 5, errors: 0,
    ...extra,
  });

  it("shows the headline the growth formatter rendered as nothing", () => {
    expect(runStatsChunks(wl()).map((c) => c.text).join(" · ")).toBe("");
    expect(welcomeStatsChunks(wl()).map((c) => c.text).join(" · "))
      .toContain("welcomed 5");
  });

  it("NEVER lets a failed tick read as a bare ok", () => {
    const chunks = welcomeStatsChunks(wl({ welcomes_sent: 0, errors: 9 }));
    expect(chunks[0]?.text).toBe("9 failed");
    expect(chunks[0]?.tone).toBe("err");
  });

  it("warns on a tick that welcomed nobody, and says why", () => {
    const chunks = welcomeStatsChunks(wl({
      welcomes_sent: 0, skipped_existing: 4, skipped_cooldown: 1, batch_capped: true,
    }));
    expect(chunks.find((c) => c.text === "welcomed 0")?.tone).toBe("warn");
    const s = chunks.map((c) => c.text).join(" · ");
    expect(s).toContain("4 already welcomed");
    expect(s).toContain("1 on cooldown");
    expect(s).toContain("batch cap hit");
  });

  it("suppresses the qualifiers that are zero", () => {
    const s = welcomeStatsChunks(wl()).map((c) => c.text).join(" · ");
    expect(s).not.toContain("already welcomed");
    expect(s).not.toContain("cooldown");
    expect(s).not.toContain("failed");
  });

  it("carries the follow-back lane, which is shared with the growth bag", () => {
    const s = welcomeStatsChunks(wl({
      follow_back: true, follow_back_gate: true, followed_back: 3,
    })).map((c) => c.text).join(" · ");
    expect(s).toContain("followed back 3");
  });

  it("reports the stop_on_reply outcomes nothing else in the app shows", () => {
    const s = welcomeStatsChunks(wl({
      aborted_on_reply: 2, handoff_enqueued: 1, reply_guard_off: 3,
    })).map((c) => c.text).join(" · ");
    expect(s).toContain("2 stopped, he replied");
    expect(s).toContain("1 handed to the chat engine");
    expect(s).toContain("3 sent without the reply guard");
  });
});

describe("runStatsChunks — a backfill preview that is standing still", () => {
  it("names the pool the dry run is not draining", () => {
    const chunks = runStatsChunks(gated({
      action: "follow", dry_run: true, candidates: 20, examined: 20,
      eligible: 3663, would_follow: [], already_following: 20,
    }));
    const e = chunks.find((c) => c.text.startsWith("3663 eligible"));
    expect(e).toBeDefined();
    expect(e?.tone).toBe("warn");
  });

  it("stays quiet when the pool fits in one look", () => {
    expect(line(gated({ source: "all_stored", candidates: 9, examined: 9, eligible: 9 })))
      .not.toContain("eligible");
  });

  it("does not call a LIVE tick's remaining pool a dry run", () => {
    const chunks = runStatsChunks({
      action: "follow", dry_run: false, source: "all_stored",
      candidates: 150, followed: 30, eligible: 3663, errors: 0,
    });
    const e = chunks.find((c) => c.text.includes("eligible"));
    expect(e?.text).toBe("3663 eligible still to walk");
    expect(e?.tone).toBeUndefined();
  });

  it("still reads an OLD stored row that stacked the two, without comparing them", () => {
    const chunks = runStatsChunks(gated({
      dry_run: true,
      source: "expired,all_stored", candidates: 40, examined: 40, eligible: 12,
    }));
    const e = chunks.find((c) => c.text.includes("eligible"));
    expect(e?.text).toBe(
      "12 eligible in the backfill pool — a dry run re-checks this same head each tick");
    expect(e?.tone).toBe("warn");
  });
});
