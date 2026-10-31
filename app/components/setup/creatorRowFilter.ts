/**
 * The Creators table's row filters (AccountsTable), one rule each for an account row and a Done-saved draft row, so
 * the two lists cannot drift. A filter whose read failed applies nothing to an account row: `picked` is undefined when
 * the Employee read failed, `connWired` false when the health read did. A draft reads no health, so `connWired` does
 * not touch it.
 */
import type { CreatorFilters } from "@/components/setup/CreatorFilterBar";
import type { Employee } from "@/lib/relay";

export interface RowFilter {
  filters: CreatorFilters;
  /** The Employee the Employee filter picked; `account_ids` null grants every Creator (`_creator_access`,
   *  service/employees.py). */
  picked?: Pick<Employee, "account_ids">;
  connWired: boolean;
}

export interface AccountRow {
  id: string;
  /** What the search matches: nickname, id, Creator name. */
  names: Array<string | null | undefined>;
  platform?: string | null;
  tag?: string;
  isActive: boolean;
  /** The row's connectivity label, read only when the Connectivity filter is on. */
  conn: () => string;
}

function matches(q: string, names: Array<string | null | undefined>): boolean {
  const needle = q.trim().toLowerCase();
  return !needle || names.some((x) => (x ?? "").toLowerCase().includes(needle));
}

export function keepAccount(a: AccountRow, { filters: f, picked, connWired }: RowFilter): boolean {
  return matches(f.q, a.names)
    && (!f.platform || (a.platform ?? "onlyfans") === f.platform)
    && (!f.tag || a.tag === f.tag)
    && (!f.conn || !connWired || a.conn() === f.conn)
    && (!f.status || a.isActive === (f.status === "Activated"))
    && (!picked || picked.account_ids == null || picked.account_ids.includes(a.id));
}

/** A draft has no platform, Tag or Employee, is activated, and reads "Pending connection" (Infloww's Creator row with
 *  no account), so any of those filters but that label hides it. */
export function keepDraft(name: string, { filters: f, picked }: RowFilter): boolean {
  return matches(f.q, [name]) && !f.platform && !f.tag && !picked && f.status !== "Deactivated"
    && (!f.conn || f.conn === "Pending connection");
}
