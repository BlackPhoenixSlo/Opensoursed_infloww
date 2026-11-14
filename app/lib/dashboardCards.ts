/**
 * The Dashboard's cards: which exist, in the Dashboard's fixed order, and the per-card permissions a Permission role
 * can hide them with.
 *
 * `CARD_PERMISSIONS` is the Relay's `permissions.CARD_KEYS` (service/tests/test_dashboard_cards.py pins this copy):
 * each key `/#card-<id>` is stored in the role's `permissions` map like a Function permission. A key stored false
 * hides the card, and the Relay refuses the Dashboard's routes that only hidden cards read; a missing key falls back
 * to the Dashboard's grant, but the built-in Chatter hides the `revenue` cards (lib/roles.ts). The cards without a
 * key are the shift cards: personal shifts for chatters, the agency schedule and worked hours for owners.
 *
 * The dashboard shows earnings, shifts, employee sales, worked hours, then the Per-model KPIs (creator) cards at the
 * bottom (removed in #374, back by owner request 2026-11-14).
 */

export const CARD_PERMISSIONS = {
  "/#card-earnings": { label: "Creator earnings overview", revenue: true },
  "/#card-employee-sales": { label: "Employee sales", revenue: true },
  "/#card-per-model": { label: "Per-model KPIs", revenue: true },
} as const satisfies Record<string, { label: string; revenue: boolean }>;

export type CardPermissionKey = keyof typeof CARD_PERMISSIONS;

/** The keys of the cards that show earnings: hidden for the built-in Chatter. */
export const REVENUE_CARD_KEYS = (Object.keys(CARD_PERMISSIONS) as CardPermissionKey[])
  .filter((k) => CARD_PERMISSIONS[k].revenue);

/** The per-card permissions under page `href` (only the Dashboard has any), `[key, label]` in list order. */
export const pageCards = (href: string): [string, string][] =>
  href === "/" ? Object.entries(CARD_PERMISSIONS).map(([key, { label }]) => [key, label]) : [];

export type DashboardCardId =
  | "earnings" | "my-shifts" | "employee-sales" | "scheduled-hours" | "per-model";

export interface DashboardCard {
  id: DashboardCardId;
  /** The grid cell: phones one column, from `md` a 12-column grid. Literal classes, for Tailwind. */
  span: string;
}

const FULL = "md:col-span-2";
const RIGHT = "md:col-start-2";

/** Every card, in the Dashboard's order. My shifts spans the two rows the cards beside it take, as its left column
 *  did (capture #64-#68). */
export const DASHBOARD_CARDS: readonly DashboardCard[] = [
  { id: "earnings", span: FULL },
  { id: "my-shifts", span: "md:col-start-1 md:row-span-2" },
  { id: "employee-sales", span: RIGHT },
  { id: "scheduled-hours", span: RIGHT },
  { id: "per-model", span: FULL },
];

/** The right-column cards (their span is RIGHT), beside My shifts. */
const RIGHT_COLUMN: readonly DashboardCardId[] = DASHBOARD_CARDS.filter((c) => c.span === RIGHT).map((c) => c.id);

/** The grid cell of `id` among the `visible` cards: its own span, except that My shifts with no card beside it, or a
 *  right-column card with no My shifts to sit beside, takes the full width rather than leave a column empty (#20). */
export function cardSpan(id: DashboardCardId, visible: readonly DashboardCardId[]): string {
  const own = DASHBOARD_CARDS.find((c) => c.id === id)!.span;
  if (id === "my-shifts" && !visible.some((v) => RIGHT_COLUMN.includes(v))) return FULL;
  if (RIGHT_COLUMN.includes(id) && !visible.includes("my-shifts")) return FULL;
  return own;
}

/** A card's permission key, or null for a card no role hides. */
export function cardKey(id: DashboardCardId): CardPermissionKey | null {
  const key = `/#card-${id}`;
  return key in CARD_PERMISSIONS ? (key as CardPermissionKey) : null;
}
