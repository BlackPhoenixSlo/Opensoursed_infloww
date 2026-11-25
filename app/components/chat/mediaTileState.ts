export type MediaTileState =
  | { kind: "loading" }
  | { kind: "loaded"; url: string }
  | { kind: "failed"; at: string };

export type MediaTileAction =
  | { type: "loaded"; url: string }
  | { type: "failed"; at: string };

export const MEDIA_TILE_INIT: MediaTileState = { kind: "loading" };

export function mediaTileReducer(s: MediaTileState, a: MediaTileAction): MediaTileState {
  switch (a.type) {
    case "loaded":
      return s.kind === "loaded" && s.url === a.url ? s : { kind: "loaded", url: a.url };
    case "failed":
      return s.kind === "failed" && s.at === a.at ? s : { kind: "failed", at: a.at };
  }
}

// A failed tile retries only on a new url (OF re-signed it), never the one that failed.
export function mediaTileLoadKey(s: MediaTileState, proxiedUrl: string): string {
  if (!proxiedUrl) return "";
  if (s.kind !== "failed") return "load";
  return s.at === proxiedUrl ? "" : proxiedUrl;
}
