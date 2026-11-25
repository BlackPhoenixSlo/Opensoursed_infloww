import type { CreatorFilters } from "@/components/setup/CreatorFilterBar";
import { accountPlatform } from "@/lib/platform";
import type { Employee } from "@/lib/relay";

export interface RowFilter {
  filters: CreatorFilters;
  picked?: Pick<Employee, "account_ids">;
  connWired: boolean;
}

export interface AccountRow {
  id: string;
  names: Array<string | null | undefined>;
  platform?: string | null;
  tag?: string;
  isActive: boolean;
  conn: () => string;
}

function matches(q: string, names: Array<string | null | undefined>): boolean {
  const needle = q.trim().toLowerCase();
  return !needle || names.some((x) => (x ?? "").toLowerCase().includes(needle));
}

export function keepAccount(a: AccountRow, { filters: f, picked, connWired }: RowFilter): boolean {
  return matches(f.q, a.names)
    && (!f.platform || accountPlatform(a) === f.platform)
    && (!f.tag || a.tag === f.tag)
    && (!f.conn || !connWired || a.conn() === f.conn)
    && (!f.status || a.isActive === (f.status === "Activated"))
    // account_ids null grants every Creator.
    && (!picked || picked.account_ids == null || picked.account_ids.includes(a.id));
}

export function keepDraft(name: string, { filters: f, picked }: RowFilter): boolean {
  return matches(f.q, [name]) && !f.platform && !f.tag && !picked && f.status !== "Deactivated"
    && (!f.conn || f.conn === "Pending connection");
}
