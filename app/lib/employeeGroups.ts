"use client";


import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export interface EmployeeGroup {
  id: number;
  name: string;
  parent_id: number | null;
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
