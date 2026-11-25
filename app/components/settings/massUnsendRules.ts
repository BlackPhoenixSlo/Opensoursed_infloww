import { runFanOut } from "@/components/compose/fanOut";
import type { MassMessageRow } from "@/hooks/useMassMessages";

export type BulkAction = "all" | "non-image" | "with-image" | "free-text-old";

export function hasImageMedia(m: MassMessageRow): boolean {
  return (m.mediaCount ?? 0) > 0;
}

export const BULK_MIN_AGE_H = 4;

// "Unsend all" ignores this gate on purpose so fresh sends can still be pulled.
export function olderThanHours(m: MassMessageRow, hours: number, now: number): boolean {
  if (!m.date) return false;
  const t = new Date(m.date).getTime();
  if (Number.isNaN(t)) return false;
  return (now - t) / 3_600_000 >= hours;
}

export function isFreeTextOld(m: MassMessageRow, now: number): boolean {
  return !!m.isFree && !hasImageMedia(m) && olderThanHours(m, BULK_MIN_AGE_H, now);
}

function inScope(r: MassMessageRow, models: ReadonlySet<string>): boolean {
  return models.size === 0 || (!!r.__accountId && models.has(r.__accountId));
}

export function visibleMassRows(
  rows: MassMessageRow[],
  models: ReadonlySet<string>,
  hideUnsent: boolean,
): MassMessageRow[] {
  let out = rows.filter((r) => inScope(r, models));
  if (hideUnsent) out = out.filter((r) => !r.isCanceled);
  return out;
}

export type ActionableRow = MassMessageRow & { __accountId: string };

export function isActionable(r: MassMessageRow): r is ActionableRow {
  return !!r.canUnsend && !r.isCanceled && !!r.__accountId;
}

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

export function bulkTargets(
  rows: MassMessageRow[],
  models: ReadonlySet<string>,
  action: BulkAction,
  now: number,
): ActionableRow[] {
  return rows.filter((r): r is ActionableRow => inScope(r, models) && isActionable(r) && matchesBulk(action, r, now));
}

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
  {
    action: "free-text-old",
    label: `Unsend free text >${BULK_MIN_AGE_H}h`,
    confirm: `Unsend FREE text-only broadcasts older than ${BULK_MIN_AGE_H}h`,
    title: `Free (no price), no image, older than ${BULK_MIN_AGE_H}h — leaves PPV/image blasts alone`,
  },
];

export function bulkCounts(
  rows: MassMessageRow[],
  models: ReadonlySet<string>,
  now: number,
): Record<BulkAction, number> {
  const out: Record<BulkAction, number> = { all: 0, "non-image": 0, "with-image": 0, "free-text-old": 0 };
  for (const { action } of BULK_ACTIONS) out[action] = bulkTargets(rows, models, action, now).length;
  return out;
}

// One OF delete in flight, Creator by Creator: the relay's 11 s write gate would make 200 unsends a 36 min run and block that Creator's automation.
export async function unsendByCreator(
  targets: readonly ActionableRow[],
  cancel: (row: ActionableRow) => Promise<unknown>,
  onProgress?: (done: number, total: number) => void,
): Promise<number> {
  const byCreator = new Map<string, ActionableRow[]>();
  for (const r of targets) {
    const list = byCreator.get(r.__accountId);
    if (list) list.push(r);
    else byCreator.set(r.__accountId, [r]);
  }
  let failed = 0;
  let done = 0;
  await runFanOut([...byCreator.keys()], async (accountId) => {
    for (const r of byCreator.get(accountId) ?? []) {
      try {
        await cancel(r);
      } catch {
        failed += 1;
      }
      onProgress?.(++done, targets.length);
    }
  });
  return failed;
}
