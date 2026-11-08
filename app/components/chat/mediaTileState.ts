/**
 * MediaTile's load (MediaTile.tsx) as one state: loading (the skeleton), loaded (the bytes' object url) or failed
 * (the url whose load failed). A failed tile is retried only on a new url (OnlyFans re-signed it), never on the one
 * that failed, and through the same lazy observer as a first load.
 */

export type MediaTileState =
  | { kind: "loading" }
  | { kind: "loaded"; url: string }
  | { kind: "failed"; at: string };

export type MediaTileAction =
  /** The bytes are in: `url` is their object url. */
  | { type: "loaded"; url: string }
  /** The load of `at` failed (not an abort). */
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

/** What the load effect is keyed on: "" when there is nothing to load (no url, or a failed tile still on the url
 *  that failed), the new url for a failed tile's retry, else "load" (the first load, or a new image). */
export function mediaTileLoadKey(s: MediaTileState, proxiedUrl: string): string {
  if (!proxiedUrl) return "";
  if (s.kind !== "failed") return "load";
  return s.at === proxiedUrl ? "" : proxiedUrl;
}
