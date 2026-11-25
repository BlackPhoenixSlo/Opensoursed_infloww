export const CARD_PERMISSIONS = {
  "/#card-earnings": { label: "Creator earnings overview", revenue: true },
  "/#card-employee-sales": { label: "Employee sales", revenue: true },
  "/#card-per-model": { label: "Per-model KPIs", revenue: true },
} as const satisfies Record<string, { label: string; revenue: boolean }>;

export type CardPermissionKey = keyof typeof CARD_PERMISSIONS;

export const REVENUE_CARD_KEYS = (Object.keys(CARD_PERMISSIONS) as CardPermissionKey[])
  .filter((k) => CARD_PERMISSIONS[k].revenue);

export const pageCards = (href: string): [string, string][] =>
  href === "/" ? Object.entries(CARD_PERMISSIONS).map(([key, { label }]) => [key, label]) : [];

export type DashboardCardId =
  | "earnings" | "my-shifts" | "employee-sales" | "scheduled-hours" | "per-model";

export interface DashboardCard {
  id: DashboardCardId;
  span: string;
}

const FULL = "md:col-span-2";
const RIGHT = "md:col-start-2";

export const DASHBOARD_CARDS: readonly DashboardCard[] = [
  { id: "earnings", span: FULL },
  { id: "my-shifts", span: "md:col-start-1 md:row-span-2" },
  { id: "employee-sales", span: RIGHT },
  { id: "scheduled-hours", span: RIGHT },
  { id: "per-model", span: FULL },
];

const RIGHT_COLUMN: readonly DashboardCardId[] = DASHBOARD_CARDS.filter((c) => c.span === RIGHT).map((c) => c.id);

export function cardSpan(id: DashboardCardId, visible: readonly DashboardCardId[]): string {
  const own = DASHBOARD_CARDS.find((c) => c.id === id)!.span;
  if (id === "my-shifts" && !visible.some((v) => RIGHT_COLUMN.includes(v))) return FULL;
  if (RIGHT_COLUMN.includes(id) && !visible.includes("my-shifts")) return FULL;
  return own;
}

export function cardKey(id: DashboardCardId): CardPermissionKey | null {
  const key = `/#card-${id}`;
  return key in CARD_PERMISSIONS ? (key as CardPermissionKey) : null;
}
