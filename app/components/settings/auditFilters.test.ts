import { describe, expect, it } from "vitest";

import {
  AUDIT_PAGE, INITIAL_AUDIT_FILTERS, auditFiltersReducer, buildAuditQuery, isFiltered,
  type AuditAction, type AuditFilters,
} from "@/components/settings/auditFilters";

const paged: AuditFilters = { ...INITIAL_AUDIT_FILTERS, offset: 2 * AUDIT_PAGE };

describe("auditFiltersReducer", () => {
  it.each<[string, AuditAction, Partial<AuditFilters>]>([
    ["employee resets the page", { type: "employee", id: 4 }, { offset: 0, employeeId: 4 }],
    ["account resets the page", { type: "account", id: "a1" }, { offset: 0, accountId: "a1" }],
    ["from resets the page", { type: "from", day: "2026-10-01" }, { offset: 0, fromDay: "2026-10-01" }],
    ["to resets the page", { type: "to", day: "2026-10-03" }, { offset: 0, toDay: "2026-10-03" }],
    ["system resets the page", { type: "system", on: true }, { offset: 0, system: true }],
    ["older moves one page on", { type: "page", dir: "older" }, { offset: 3 * AUDIT_PAGE }],
    ["newer moves one page back", { type: "page", dir: "newer" }, { offset: AUDIT_PAGE }],
  ])("%s", (_, action, want) => {
    expect(auditFiltersReducer(paged, action)).toEqual({ ...paged, ...want });
  });

  it("newer never goes below 0", () => {
    expect(auditFiltersReducer(INITIAL_AUDIT_FILTERS, { type: "page", dir: "newer" }).offset).toBe(0);
  });
});

describe("buildAuditQuery", () => {
  it.each<[string, Partial<AuditFilters>, Record<string, string | null>]>([
    ["defaults hide system writes", {}, { limit: "50", offset: "0", include_background: null, account_id: null }],
    ["system box asks for everything", { system: true }, { include_background: "true" }],
    ["employee + account", { employeeId: 7, accountId: "acc" }, { employee_id: "7", account_id: "acc" }],
    ["days become UTC bounds, to inclusive", { fromDay: "2026-10-01", toDay: "2026-10-03" },
      { from: new Date(2026, 9, 1).toISOString(), to: new Date(2026, 9, 4).toISOString() }],
    ["partial day is ignored", { fromDay: "2026-10" }, { from: null }],
  ])("%s", (_, patch, want) => {
    const qs = new URLSearchParams(buildAuditQuery({ ...INITIAL_AUDIT_FILTERS, ...patch }));
    for (const [k, v] of Object.entries(want)) expect(qs.get(k)).toBe(v);
  });
});

describe("isFiltered", () => {
  it.each<[Partial<AuditFilters>, boolean]>([
    [{}, false],
    [{ system: true }, false],
    [{ employeeId: 1 }, true],
    [{ accountId: "a" }, true],
    [{ toDay: "2026-10-03" }, true],
  ])("%j → %s", (patch, want) => {
    expect(isFiltered({ ...INITIAL_AUDIT_FILTERS, ...patch })).toBe(want);
  });
});
