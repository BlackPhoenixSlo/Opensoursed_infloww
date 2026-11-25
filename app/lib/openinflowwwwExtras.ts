import { BRAND_NAME } from "@/lib/brand";

export const EXTRA_LABEL = `${BRAND_NAME} extra`;

export const EXTRAS_OVERFLOW_LABEL = `${BRAND_NAME} extras`;

export type Host =
  | "Window header"
  | "Fan List" | "Fan List sort menu"
  | "Chat header overflow"
  | "Fan insights";

export type Extra = {
  name: string;
  hosts: readonly Host[];
};

export const EXTRAS = [
  { name: "Scheduled chip", hosts: ["Chat header overflow"] },
  { name: "Owe reply", hosts: ["Fan List"] },
  { name: "Priority chip", hosts: ["Fan List"] },
  { name: "Group chat", hosts: ["Chat header overflow"] },
  { name: "All Models", hosts: ["Window header"] },
  { name: "Generated profile note", hosts: ["Fan insights"] },
  { name: "Persona claims", hosts: ["Fan insights"] },
  { name: "Mass exclude", hosts: ["Chat header overflow", "Fan insights"] },
  { name: "Mark as unread", hosts: ["Chat header overflow"] },
  { name: "Fan identity", hosts: ["Fan insights"] },
  { name: "Unsold PPVs", hosts: ["Fan insights"] },
  {
    name: "Extra sort orders",
    hosts: ["Fan List sort menu", "Fan List sort menu", "Fan List sort menu"],
  },
] as const satisfies readonly Extra[];

export type ExtraName = (typeof EXTRAS)[number]["name"];

export function extraTitle(name: ExtraName, detail?: string): string {
  const first = `${EXTRA_LABEL} — ${name}`;
  return detail ? `${first}\n${detail}` : first;
}
