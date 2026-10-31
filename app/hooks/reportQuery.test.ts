/**
 * reportQuery — the report window + model + employee every /admin report list sends, and the three builders on top
 * of it pinned to the exact strings they sent before it was shared. Every identifier is invented.
 */
import { describe, expect, it } from "vitest";

import { reportQuery } from "@/hooks/reportQuery";
import { buildPaidMessagesQuery } from "@/hooks/usePaidMessages";
import { buildTipsListQuery } from "@/hooks/useTipsList";
import { buildTopTippersQuery } from "@/hooks/useTopTippers";

const ALL = { from: "2026-10-01", to: "2026-10-02", account_id: "100000001", employee_id: 5 };
const NONE = { from: null, to: null, account_id: null, employee_id: null };

describe("reportQuery", () => {
  it.each([
    ["all set", ALL, "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5"],
    ["empties omitted", { from: "", to: "", account_id: "", employee_id: null }, ""],
    ["nulls omitted", NONE, ""],
    ["undefined model + employee omitted", { from: "2026-10-01", to: "2026-10-02" }, "from=2026-10-01&to=2026-10-02"],
    // No "all" sentinel: the filters send null for All models, so a literal "all" goes on the wire as given.
    ["\"all\" account sent as given", { ...NONE, account_id: "all" }, "account_id=all"],
    ["employee only", { ...NONE, employee_id: 5 }, "employee_id=5"],
    ["employee 0 kept", { ...NONE, employee_id: 0 }, "employee_id=0"],
    ["encoding", { from: "2026-10-01T00:00:00+02:00", to: "a b&c", account_id: "x/y", employee_id: null },
      "from=2026-10-01T00%3A00%3A00%2B02%3A00&to=a+b%26c&account_id=x%2Fy"],
  ])("%s", (_name, params, want) => {
    expect(reportQuery(params).toString()).toBe(want);
  });
});

describe("the builders' strings, unchanged", () => {
  it("paid messages: list, page 2, csv", () => {
    const p = { ...ALL, status: "paid" as const, type: "all" as const, direction: "any" as const, fan_query: "ann" };
    expect(buildPaidMessagesQuery(p)).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&status=paid&type=all&direction=any&fan_query=ann&limit=50");
    expect(buildPaidMessagesQuery(p, { sent_at: "2026-10-01T10:00:00", id: 77 })).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&status=paid&type=all&direction=any&fan_query=ann&limit=50&before_id=77&before_sent_at=2026-10-01T10%3A00%3A00");
    expect(buildPaidMessagesQuery(p, null, { format: "csv" })).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&status=paid&type=all&direction=any&fan_query=ann&format=csv");
    expect(buildPaidMessagesQuery({ ...NONE, account_id: "all" })).toBe("account_id=all&limit=50");
  });

  it("tips list: list, page 2, csv", () => {
    const p = { ...ALL, fan_query: "ann" };
    expect(buildTipsListQuery(p, null)).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&fan_query=ann&limit=50");
    expect(buildTipsListQuery(p, 77)).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&fan_query=ann&limit=50&before_id=77");
    expect(buildTipsListQuery(p, 77, true)).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&fan_query=ann&format=csv");
    expect(buildTipsListQuery({ ...NONE, employee_id: 5 }, null)).toBe("employee_id=5&limit=50");
  });

  it("top tippers: list, limit, csv", () => {
    expect(buildTopTippersQuery(ALL)).toBe("from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5");
    expect(buildTopTippersQuery({ ...ALL, limit: 20 })).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&limit=20");
    expect(buildTopTippersQuery({ ...ALL, limit: 20 }, true)).toBe(
      "from=2026-10-01&to=2026-10-02&account_id=100000001&employee_id=5&format=csv");
    expect(buildTopTippersQuery({ ...NONE, account_id: "all" })).toBe("account_id=all");
  });
});
