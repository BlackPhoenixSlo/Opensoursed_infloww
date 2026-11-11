import { describe, expect, it } from "vitest";

import { type DashboardCardId, cardSpan, DASHBOARD_CARDS } from "@/lib/dashboardCards";

const ALL = DASHBOARD_CARDS.map((c) => c.id);
const own = (id: DashboardCardId) => DASHBOARD_CARDS.find((c) => c.id === id)!.span;

describe("cardSpan (#20)", () => {
  it.each<[string, DashboardCardId[], DashboardCardId, string]>([
    ["every card: My shifts keeps its left column", ALL, "my-shifts", own("my-shifts")],
    ["every card: a right card keeps the right column", ALL, "employee-sales", own("employee-sales")],
    ["a chatter's sole My shifts takes the full width", ["my-shifts"], "my-shifts", "md:col-span-2"],
    ["My shifts beside the earnings card only: full width", ["earnings", "my-shifts"], "my-shifts", "md:col-span-2"],
    ["My shifts beside one right card keeps its column", ["my-shifts", "employee-sales"], "my-shifts", own("my-shifts")],
    ["a right card with no My shifts takes the full width", ["earnings", "scheduled-hours"], "scheduled-hours", "md:col-span-2"],
    ["a sole Employee sales takes the full width", ["employee-sales"], "employee-sales", "md:col-span-2"],
    ["earnings is always full width", ["earnings"], "earnings", "md:col-span-2"],
  ])("%s", (_name, visible, id, want) => {
    expect(cardSpan(id, visible)).toBe(want);
  });
});
