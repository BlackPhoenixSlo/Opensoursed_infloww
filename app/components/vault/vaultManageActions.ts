/** The Vault manager's actions (moved out of `VaultManagePanel`): plain async functions, no React. The panel only
 *  wires them — it hands each the deps it reads and the one `busy` line they share. */

import { type QueryClient } from "@tanstack/react-query";

import {
  addToOfFolder,
  cacheSummaryKey,
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

/** A vault item as the manager holds it: the mirror row plus its describe read-out. */
export type Tile = VaultMedia & { _ai?: Record<string, unknown> };

/** The panel's one busy line ("describing 3/10", "adding to OF…"). `get` reads it synchronously (a ref), so a second
 *  call in the same tick sees the first one's mark — the button's `disabled` only lands on the next render. */
export interface Busy {
  get: () => string;
  set: (s: string) => void;
}

/** What the panel hands every action: the account, the query cache and the busy line, plus the bits of its state an
 *  action reads or resets. */
export interface ManageDeps {
  accountId: string;
  qc: QueryClient;
  busy: Busy;
  /** The ticked files (`vaultBrowseReducer`). */
  selected: ReadonlySet<number>;
  clearSelection: () => void;
  /** Everything that answers "what is in this vault" — `invalidateVaultGrid`. */
  refreshAll: () => void;
  /** The server's sentence for the AI cap (`VisionCapState.blocked_reason`). */
  capReason: string;
  refetchPlan: () => void;
}

export async function onCollect(d: Pick<ManageDeps, "accountId" | "qc" | "refreshAll"> & { isCollecting: boolean }) {
  const { accountId, qc } = d;
  if (d.isCollecting) return;
  try {
    await startCollect(accountId);
  } catch {
    /* already running */
  }
  qc.invalidateQueries({ queryKey: cacheSummaryKey(accountId) });
  for (let i = 0; i < 4; i++) {
    await new Promise((r) => setTimeout(r, 2500));
    qc.invalidateQueries({ queryKey: cacheSummaryKey(accountId) });
    const st = await fetchCollectStatus(accountId).catch(() => null);
    if (st?.run && (st.run.total_seen ?? 0) > 0) {
      d.refreshAll();
      break;
    }
  }
}

export async function onDescribeAll(
  mode: "new" | "restage" | "force",
  d: Pick<ManageDeps, "capReason" | "refetchPlan"> & {
    describeSweep: Pick<VaultSweep, "busy" | "start">;
    capped: boolean;
    plan: { total?: number; restage?: number } | undefined;
    promptVersion: "v1" | "v2";
  },
) {
  const { describeSweep, capped, capReason, promptVersion } = d;
  if (describeSweep.busy) return;
  if (capped) {
    // Reachable with a plan up to 30s stale (its staleTime) — the button is
    // already grey once the refetch lands. Say it rather than no-op.
    window.alert(capReason);
    d.refetchPlan();
    return;
  }
  if (mode !== "new") {
    const n = mode === "force" ? (d.plan?.total ?? 0) : (d.plan?.restage ?? 0);
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
    if (!window.confirm(`${what} with prompt ${promptVersion.toUpperCase()}?\n\n` +
        `Estimated ~$${est.toFixed(2)} of LLM spend against today's cap.`)) {
      return;
    }
  }
  await describeSweep.start(describeAllBody({
    force: mode === "force",
    restage: mode === "restage",
    promptVersion,
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

/** Describe the ticked files, one paid LLM call each. */
export async function describeSelected(d: ManageDeps) {
  const { accountId, busy, selected, capReason } = d;
  if (selected.size === 0 || busy.get()) return;
  const ids = [...selected];
  // STOPS on the cap rather than grinding through the rest: every remaining
  // call would be refused before it fires, so continuing only keeps the
  // operator watching a counter that describes nothing. One exit either way.
  let stopped = "";
  for (let i = 0; i < ids.length && !stopped; i++) {
    busy.set(`describing ${i}/${ids.length}`);
    const r = await describeMedia(accountId, ids[i]).catch((e) => {
      if (e instanceof ApiKeyError) stopped = "key"; // toasted by relay.ts; stop, don't repeat it per item
      return null;
    });
    if (r?.status === "capped") {
      // `detail` and `capReason` are the same sentence from the same author
      // (the relay's `_vision_budget`) — this only picks whichever arrived.
      stopped = `${r.detail ?? capReason}\n\n` +
        `Described ${i} of ${ids.length} before the cap.`;
    }
  }
  busy.set("");
  d.clearSelection();
  d.qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  if (stopped) {
    d.refetchPlan();
    if (stopped !== "key") window.alert(stopped);
  }
}

/** The busy line while `describeOne` runs — the drawer's Describe button reads it to say "Describing…". */
export const DESCRIBING = "describing";

/** Describe the open item — one paid LLM call. */
export async function describeOne(m: Tile, d: ManageDeps & { setPreview: (t: Tile) => void }) {
  const { accountId, busy } = d;
  if (busy.get()) return;
  busy.set(DESCRIBING);
  try {
    const r = await describeMedia(accountId, m.id);
    if (r.status === "capped") {
      d.refetchPlan();
      window.alert(r.detail ?? d.capReason);
      return;
    }
    d.setPreview({ ...m, _ai: { ...(m._ai ?? {}), ...r } });
    d.qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  } catch (e) {
    if (!(e instanceof ApiKeyError)) throw e; // the key toast already says why
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
