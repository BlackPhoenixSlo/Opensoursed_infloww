/** The Inflowwww folders editor's item viewer and the full-screen player over it: one reducer, since the player
 *  decides what Escape closes and gates the viewer's arrow keys. */
import type { Tile } from "@/components/vault/vaultManageActions";

export interface ViewerState {
  preview: Tile | null;
  play: Tile | null;
}

export type ViewerAction =
  | { type: "open"; media: Tile }
  | { type: "play"; media: Tile }
  | { type: "expand" }
  | { type: "closePlayer" }
  | { type: "close" }
  | { type: "escape" }
  | { type: "saved"; mediaId: number; updated: Record<string, unknown> };

/** The keys of an item edit's response (`_item_edit_view`) that live in a tile's `_ai` (`_overlay`); the rest
 *  (`media_id`, `id`, `kind`, `locked_fields`) are not `_ai`'s. */
const AI_KEYS = [
  "describe_status", "description", "video_description", "tags", "explicitness_tier", "suggested_caption",
  "suggested_script", "suggested_price_cents", "fields", "jev_picks", "jev_ai",
] as const;

export const INITIAL_VIEWER: ViewerState = { preview: null, play: null };

export function viewerReducer(s: ViewerState, a: ViewerAction): ViewerState {
  switch (a.type) {
    case "open":
      return { ...s, preview: a.media };
    case "play":
      return { ...s, play: a.media };
    case "expand":
      return s.preview ? { ...s, play: s.preview } : s;
    case "closePlayer":
      return { ...s, play: null };
    case "close":
      return INITIAL_VIEWER;
    case "escape":
      // The player is on top: it goes first, the viewer on the next press.
      return s.play ? { ...s, play: null } : { ...s, preview: null };
    case "saved": {
      // A save's answer lands only on the item it was for: stepping on before it returns leaves the next one alone.
      if (!s.preview || s.preview.id !== a.mediaId) return s;
      const ai = Object.fromEntries(AI_KEYS.filter((k) => k in a.updated).map((k) => [k, a.updated[k]]));
      return { ...s, preview: { ...s.preview, _ai: { ...(s.preview._ai ?? {}), ...ai } } };
    }
  }
}
