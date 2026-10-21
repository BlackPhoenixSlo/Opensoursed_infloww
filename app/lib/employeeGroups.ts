"use client";

/**
 * The Agency's Employee groups (`GET /admin/employee-groups`, service/employee_groups_api.py;
 * docs/spec/phase-05-remaining-parity-gaps.md, item 4): one query that Manage employees' group tree,
 * phone group select and Batch edit group, and Sales records' Employees filter share. Owner session or Master
 * only; the Relay refuses a chatter 403.
 */

import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export interface EmployeeGroup {
  id: number;
  name: string;
  /** null = directly under the Agency root. */
  parent_id: number | null;
  /** Every Employee placed in the group, deactivated ones included. */
  employee_count: number;
}

export const GROUPS_KEY = ["employee-groups"];

export function useEmployeeGroups(enabled = true) {
  return useQuery({
    queryKey: GROUPS_KEY,
    queryFn: () => relay.get<{ groups: EmployeeGroup[] }>("/admin/employee-groups"),
    enabled,
  });
}

/** The groups depth first under the Agency root, each with its depth (0 = directly under the root). */
export function groupsInTreeOrder(groups: EmployeeGroup[]): Array<{ group: EmployeeGroup; depth: number }> {
  const out: Array<{ group: EmployeeGroup; depth: number }> = [];
  const walk = (parentId: number | null, depth: number) => {
    for (const g of groups.filter((x) => x.parent_id === parentId)) {
      out.push({ group: g, depth });
      walk(g.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}
