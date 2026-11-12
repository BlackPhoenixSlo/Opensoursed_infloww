/**
 * The picker's revalidate on open (VaultPicker.tsx; fetch-diet 17): the grid and the folder list paint from cache,
 * then each is read once more with `revalidate=1` (the relay serves its shared copy only when younger than
 * VAULT_PICKER_REVALIDATE_S, else asks OnlyFans) and the answer is swapped into the same query key
 * (hooks/useVaultMedia `revalidateVaultLists`, `revalidateVaultMediaFirstPage`). Armed with the filters' hydrate,
 * in the same render, so the read is for the restored folder and never for the last open's.
 */

export type RevalidateTarget = "lists" | "media";
/** armed: opened, this open's read not sent yet; idle: none due (never opened, or this open's one read went out). */
export type RevalidatePhase = "idle" | "armed";
export type RevalidateState = Record<RevalidateTarget, RevalidatePhase>;

export type RevalidateAction =
  /** The picker opened (closed → open): one read of each is due this open. */
  | { type: "open" }
  | { type: "sent"; target: RevalidateTarget };

export const revalidateInit: RevalidateState = { lists: "idle", media: "idle" };

export function revalidateReducer(s: RevalidateState, a: RevalidateAction): RevalidateState {
  switch (a.type) {
    case "open":
      return { lists: "armed", media: "armed" };
    case "sent":
      return s[a.target] === "idle" ? s : { ...s, [a.target]: "idle" };
  }
}

/** What the grid shows now, as VaultPicker reads it. */
export interface MediaPaint {
  /** The grid's source: only the live listing (useVaultMedia) is revalidated; the mirror's grid reads the mirror. */
  source: "mirror" | "live";
  /** The mirror summary has answered (or failed), so `source` is final. */
  sourceSettled: boolean;
  /** A restricted chatter's folder gate has landed and the open folder is one of his. */
  folderSettled: boolean;
  /** The open key's first page is on screen: loaded, not a placeholder, no read in flight, no error. */
  painted: boolean;
}

export const mediaReady = (p: MediaPaint): boolean =>
  p.source === "live" && p.sourceSettled && p.folderSettled && p.painted;

/** The reads to send now: each armed target whose painted copy is on screen. */
export function revalidateDue(s: RevalidateState, ready: Record<RevalidateTarget, boolean>): RevalidateTarget[] {
  return (["lists", "media"] as const).filter((t) => s[t] === "armed" && ready[t]);
}
