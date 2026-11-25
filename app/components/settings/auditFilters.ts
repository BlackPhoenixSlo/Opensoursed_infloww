export const AUDIT_PAGE = 50;

export interface AuditFilters {
  offset: number;
  employeeId: number | null;
  accountId: string | null;
  fromDay: string;
  toDay: string;
  system: boolean;
}

export type AuditAction =
  | { type: "employee"; id: number | null }
  | { type: "account"; id: string | null }
  | { type: "from"; day: string }
  | { type: "to"; day: string }
  | { type: "system"; on: boolean }
  | { type: "page"; dir: "newer" | "older" };

export const INITIAL_AUDIT_FILTERS: AuditFilters = {
  offset: 0, employeeId: null, accountId: null, fromDay: "", toDay: "", system: false,
};

export function auditFiltersReducer(s: AuditFilters, a: AuditAction): AuditFilters {
  switch (a.type) {
    case "employee": return { ...s, offset: 0, employeeId: a.id };
    case "account": return { ...s, offset: 0, accountId: a.id };
    case "from": return { ...s, offset: 0, fromDay: a.day };
    case "to": return { ...s, offset: 0, toDay: a.day };
    case "system": return { ...s, offset: 0, system: a.on };
    case "page":
      return { ...s, offset: a.dir === "older" ? s.offset + AUDIT_PAGE : Math.max(0, s.offset - AUDIT_PAGE) };
  }
}

export function isFiltered(s: AuditFilters): boolean {
  return s.employeeId != null || s.accountId != null || !!dayBound(s.fromDay, 0) || !!dayBound(s.toDay, 1);
}

export function buildAuditQuery(s: AuditFilters): string {
  const qs = new URLSearchParams();
  qs.set("limit", String(AUDIT_PAGE));
  qs.set("offset", String(s.offset));
  if (s.employeeId != null) qs.set("employee_id", String(s.employeeId));
  if (s.accountId) qs.set("account_id", s.accountId);
  const from = dayBound(s.fromDay, 0);
  const to = dayBound(s.toDay, 1);
  if (from) qs.set("from", from);
  if (to) qs.set("to", to);
  if (s.system) qs.set("include_background", "true");
  return qs.toString();
}

// plusDays 1 turns the inclusive "to" day into an exclusive bound.
export function dayBound(day: string, plusDays: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m) return "";
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + plusDays).toISOString();
}
