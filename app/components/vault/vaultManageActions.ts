import { type QueryClient } from "@tanstack/react-query";

import { ifAlert, ifConfirm } from "@/components/ui/ifConfirm";
import {
  addToOfFolder,
  answerCollect,
  cacheSummaryKey,
  type CollectRun,
  createOfFolder,
  describeAllBody,
  describeMedia,
  fetchCollectStatus,
  mirrorItemsKey,
  reorderItems,
  startCollect,
} from "@/hooks/useVaultCache";
import { type VaultSweep } from "@/hooks/useVaultSweep";
import { type FanId } from "@/lib/fanId";
import { ApiKeyError, type VaultMedia } from "@/lib/relay";

export type Tile = VaultMedia & { _ai?: Record<string, unknown> };

// `get` reads a ref: a second call in the same tick must see the first one's mark (`disabled` lands only on the next render)
export interface Busy {
  get: () => string;
  set: (s: string) => void;
}

export interface ManageDeps {
  accountId: string;
  qc: QueryClient;
  busy: Busy;
  selected: ReadonlySet<number>;
  clearSelection: () => void;
  refreshAll: () => void;
  capReason: string;
  refetchPlan: () => void;
}

export function collectHasNews(run: CollectRun | null | undefined): boolean {
  if (!run) return false;
  return (run.total_seen ?? 0) > 0 || run.phase !== "media" || run.status !== "running";
}

export async function onCollect(d: Pick<ManageDeps, "accountId" | "qc" | "refreshAll"> & { isCollecting: boolean }) {
  const { accountId, qc } = d;
  if (d.isCollecting) return;
  try {
    await startCollect(accountId);
  } catch {
  }
  qc.invalidateQueries({ queryKey: cacheSummaryKey(accountId) });
  const polls = 4;
  for (let i = 0; i < polls; i++) {
    await new Promise((r) => setTimeout(r, 2500));
    qc.invalidateQueries({ queryKey: cacheSummaryKey(accountId) });
    const st = await fetchCollectStatus(accountId).catch(() => null);
    // the last poll refreshes regardless: a restricted chatter sees no totals, so a vault still paging OF would leave its grid stale
    if (collectHasNews(st?.run) || i === polls - 1) {
      d.refreshAll();
      break;
    }
  }
}

export async function onCollectAnswer(answer: "continue" | "stop", d: Pick<ManageDeps, "accountId" | "qc">) {
  try {
    await answerCollect(d.accountId, answer);
  } catch {
  }
  d.qc.invalidateQueries({ queryKey: cacheSummaryKey(d.accountId) });
}

export const DESCRIBE_LIMIT_KEY = "vaultDescribeLimit";
export const DESCRIBE_LIMIT_DEFAULT = 2000;

export function parseDescribeLimit(raw: string | null): number {
  if (raw == null) return DESCRIBE_LIMIT_DEFAULT;
  const n = Math.floor(Number(raw.trim()));
  return raw.trim() && Number.isFinite(n) && n > 0 ? n : 0;
}

export function cappedCount(n: number, limit: number): number {
  return limit > 0 ? Math.min(n, limit) : n;
}

export async function onDescribeAll(
  mode: "new" | "restage" | "force",
  d: Pick<ManageDeps, "capReason" | "refetchPlan"> & {
    describeSweep: Pick<VaultSweep, "busy" | "start">;
    capped: boolean;
    plan: { total?: number; restage?: number } | undefined;
    promptVersion: "v1" | "v2";
    limit: number;
  },
) {
  const { describeSweep, capped, capReason, promptVersion, limit } = d;
  if (describeSweep.busy) return;
  if (capped) {
    await ifAlert(capReason);
    d.refetchPlan();
    return;
  }
  if (mode !== "new") {
    const n = cappedCount(mode === "force" ? (d.plan?.total ?? 0) : (d.plan?.restage ?? 0), limit);
    // Cents per item, MEASURED 2026-08-05 on 18 real stills at DeepInfra's
    // live rates — not the bake-off's original figures. Those were taken when
    // A sent 3 frames and B sent 9; the duration ladder now applies to BOTH,
    // so A sends exactly as many images as B and saves only on the shorter
    // output. A was quoted at 0.011 and really costs ~0.05 — a 5x under-count
    // that made the cheap option look free.
    const est = ((promptVersion === "v2" ? 0.052 : 0.046) * n) / 100;
    const what =
      mode === "force"
        ? `Re-describe ALL ${n} items`
        : `Re-scan ${n} items still on the other prompt`;
    if (!(await ifConfirm(`${what} with prompt ${promptVersion.toUpperCase()}?\n\n` +
        `Estimated ~$${est.toFixed(2)} of LLM spend against today's cap.`))) {
      return;
    }
  }
  await describeSweep.start(describeAllBody({
    force: mode === "force",
    restage: mode === "restage",
    promptVersion,
    limit,
  }));
}

export async function addSelectedToFolder(listId: FanId, d: ManageDeps) {
  const { accountId, busy, selected } = d;
  if (selected.size === 0 || busy.get()) return;
  busy.set("adding to OF…");
  try {
    await addToOfFolder(accountId, listId, [...selected]);
    d.clearSelection();
    d.refreshAll();
  } finally {
    busy.set("");
  }
}

export async function newFolderWithSelection(d: ManageDeps) {
  const { accountId, busy, selected } = d;
  if (busy.get()) return;
  const name = window.prompt("New OF folder name:");
  if (!name?.trim()) return;
  busy.set("creating OF folder…");
  try {
    await createOfFolder(accountId, name.trim(), [...selected]);
    d.clearSelection();
    d.refreshAll();
  } finally {
    busy.set("");
  }
}

export async function describeSelected(d: ManageDeps) {
  const { accountId, busy, selected, capReason } = d;
  if (selected.size === 0 || busy.get()) return;
  const ids = [...selected];
  // stop on the cap: every remaining call would be refused before it fires
  let stopped = "";
  for (let i = 0; i < ids.length && !stopped; i++) {
    busy.set(`describing ${i}/${ids.length}`);
    const r = await describeMedia(accountId, ids[i]).catch((e) => {
      if (e instanceof ApiKeyError) stopped = "key";
      return null;
    });
    if (r?.status === "capped") {
      stopped = `${r.detail ?? capReason}\n\n` +
        `Described ${i} of ${ids.length} before the cap.`;
    }
  }
  busy.set("");
  d.clearSelection();
  d.qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  if (stopped) {
    d.refetchPlan();
    if (stopped !== "key") await ifAlert(stopped);
  }
}

export const DESCRIBING = "describing";

export async function describeOne(m: Tile, d: ManageDeps & { setPreview: (t: Tile) => void }) {
  const { accountId, busy } = d;
  if (busy.get()) return;
  busy.set(DESCRIBING);
  try {
    const r = await describeMedia(accountId, m.id);
    if (r.status === "capped") {
      d.refetchPlan();
      await ifAlert(r.detail ?? d.capReason);
      return;
    }
    d.setPreview({ ...m, _ai: { ...(m._ai ?? {}), ...r } });
    d.qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  } catch (e) {
    if (!(e instanceof ApiKeyError)) throw e;
  } finally {
    busy.set("");
  }
}

export async function setOrder(
  m: VaultMedia,
  value: number | null,
  d: Pick<ManageDeps, "accountId" | "qc"> & { ofFolderId: FanId | null },
) {
  const { accountId, ofFolderId } = d;
  if (ofFolderId == null) return;
  await reorderItems(accountId, ofFolderId, [{ media_id: m.id, manual_order: value }]).catch(
    () => {},
  );
  d.qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
}
