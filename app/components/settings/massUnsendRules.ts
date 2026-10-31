/**
 * The Mass messages tab's pure row rules: which rows show, which a bulk
 * unsend picks. OF's mass unsend is irreversible, so the bulk pick is here,
 * time injected (`now`), tested in massUnsendRules.test.ts.
 */

import type { MassMessageRow } from "@/hooks/useMassMessages";

/** The bulk actions of the tab's bar; each button's key. */
export type BulkAction = "all" | "non-image" | "with-image" | "free-text-old";

/** True when the row carries non-GIF visual media (photos / videos).
 *  GIFs live under `giphyId`, not `media[]`, so GIF-only rows return
 *  false here. Used by the bulk-action filters. */
export function hasImageMedia(m: MassMessageRow): boolean {
  return (m.mediaCount ?? 0) > 0;
}

/** Age gate for every TYPED bulk action (non-image / with-images / free text) —
 *  mirrors the backend unsend_messages `policy.mass_text_hours` (a blast has
 *  done its job after this long). "Unsend all" ignores it on purpose so
 *  fresh sends can still be pulled. */
export const BULK_MIN_AGE_H = 4;

export function olderThanHours(m: MassMessageRow, hours: number, now: number): boolean {
  if (!m.date) return false; // unknown sent time → never auto-eligible
  const t = new Date(m.date).getTime();
  if (Number.isNaN(t)) return false;
  return (now - t) / 3_600_000 >= hours;
}

/** Free (no price) + image-less + older than the threshold — the exact set the
 *  backend `policy.mass_text_hours` sweep targets. GIF-only counts as image-less. */
export function isFreeTextOld(m: MassMessageRow, now: number): boolean {
  return !!m.isFree && !hasImageMedia(m) && olderThanHours(m, BULK_MIN_AGE_H, now);
}

/** In the model-chip scope: an empty set is every model. */
function inScope(r: MassMessageRow, models: ReadonlySet<string>): boolean {
  return models.size === 0 || (!!r.__accountId && models.has(r.__accountId));
}

/** The listed rows: the model chips' scope, and unsent ones dropped when hidden. */
export function visibleMassRows(
  rows: MassMessageRow[],
  models: ReadonlySet<string>,
  hideUnsent: boolean,
): MassMessageRow[] {
  let out = rows.filter((r) => inScope(r, models));
  if (hideUnsent) out = out.filter((r) => !r.isCanceled);
  return out;
}

/** A row whose Creator is known, so its cancel can route. */
export type ActionableRow = MassMessageRow & { __accountId: string };

/** A row any bulk action may unsend: OF still allows it, not unsent, its Creator known. */
export function isActionable(r: MassMessageRow): r is ActionableRow {
  return !!r.canUnsend && !r.isCanceled && !!r.__accountId;
}

/** The action's own filter, over an actionable row. */
export function matchesBulk(action: BulkAction, r: MassMessageRow, now: number): boolean {
  switch (action) {
    case "all":
      return true;
    case "non-image":
      return !hasImageMedia(r) && olderThanHours(r, BULK_MIN_AGE_H, now);
    case "with-image":
      return hasImageMedia(r) && olderThanHours(r, BULK_MIN_AGE_H, now);
    case "free-text-old":
      return isFreeTextOld(r, now);
  }
}

/** The rows a bulk `action` unsends: in the model chips' scope, actionable, and
 *  its filter's. The "Hide unsent" box never matters: an unsent row is never actionable. */
export function bulkTargets(
  rows: MassMessageRow[],
  models: ReadonlySet<string>,
  action: BulkAction,
  now: number,
): ActionableRow[] {
  return rows.filter((r): r is ActionableRow => inScope(r, models) && isActionable(r) && matchesBulk(action, r, now));
}

/** The bulk bar's buttons, in order: `label` + " (count)" is the button text,
 *  `confirm` heads the confirmation, `title` the hover hint. */
export const BULK_ACTIONS: readonly { action: BulkAction; label: string; confirm: string; title?: string }[] = [
  { action: "all", label: "Unsend all", confirm: "Unsend ALL visible broadcasts" },
  {
    action: "non-image",
    label: `Unsend non-image (GIFs incl.) >${BULK_MIN_AGE_H}h`,
    confirm: `Unsend non-image broadcasts (text + GIF + empty) older than ${BULK_MIN_AGE_H}h`,
  },
  {
    action: "with-image",
    label: `Unsend with images >${BULK_MIN_AGE_H}h`,
    confirm: `Unsend broadcasts that include images / videos, older than ${BULK_MIN_AGE_H}h`,
  },
  // The free-text cleanup — same target set as the backend unsend_messages
  // `policy.mass_text_hours` sweep: free (no price), image-less, past the age
  // gate. Keeps revenue (PPV/image) blasts.
  {
    action: "free-text-old",
    label: `Unsend free text >${BULK_MIN_AGE_H}h`,
    confirm: `Unsend FREE text-only broadcasts older than ${BULK_MIN_AGE_H}h`,
    title: `Free (no price), no image, older than ${BULK_MIN_AGE_H}h — leaves PPV/image blasts alone`,
  },
];

/** Each bulk action's target count (the button labels' numbers). */
export function bulkCounts(
  rows: MassMessageRow[],
  models: ReadonlySet<string>,
  now: number,
): Record<BulkAction, number> {
  const out: Record<BulkAction, number> = { all: 0, "non-image": 0, "with-image": 0, "free-text-old": 0 };
  for (const { action } of BULK_ACTIONS) out[action] = bulkTargets(rows, models, action, now).length;
  return out;
}
