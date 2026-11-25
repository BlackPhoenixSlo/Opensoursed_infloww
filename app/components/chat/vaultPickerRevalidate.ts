export type RevalidateTarget = "lists" | "media";
export type RevalidatePhase = "idle" | "armed";
export type RevalidateState = Record<RevalidateTarget, RevalidatePhase>;

export type RevalidateAction =
  | { type: "open" }
  | { type: "sent"; target: RevalidateTarget };

export const revalidateInit: RevalidateState = { lists: "idle", media: "idle" };

export function revalidateReducer(s: RevalidateState, a: RevalidateAction): RevalidateState {
  switch (a.type) {
    case "open":
      // Armed in the same render as the filters' hydrate, so the read is for the restored folder, not the last open's.
      return { lists: "armed", media: "armed" };
    case "sent":
      return s[a.target] === "idle" ? s : { ...s, [a.target]: "idle" };
  }
}

export interface MediaPaint {
  source: "mirror" | "live";
  sourceSettled: boolean;
  folderSettled: boolean;
  painted: boolean;
}

export const mediaReady = (p: MediaPaint): boolean =>
  p.source === "live" && p.sourceSettled && p.folderSettled && p.painted;

export function revalidateDue(s: RevalidateState, ready: Record<RevalidateTarget, boolean>): RevalidateTarget[] {
  return (["lists", "media"] as const).filter((t) => s[t] === "armed" && ready[t]);
}
