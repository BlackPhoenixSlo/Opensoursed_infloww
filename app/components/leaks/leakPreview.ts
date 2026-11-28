import { parseUtc } from "@/lib/format";
import { buildUrl } from "@/lib/relay";

import { dayLabel, seenNote, type Leak, type LeakPill, type LeakPreview } from "./leakView";

export type ThumbState = "placeholder" | "blurred" | "clear";

export const PREVIEW_LABEL = "Google preview · image may be unrelated";
export const NO_PREVIEWS = "No Google previews for this Creator yet.";
export const PREVIEW_FAILED = "Preview unavailable";
export const STRIP_MAX = 12;
export const RETRY_MS = 1500;

export type Tile = {
  key: string;
  leakId: string;
  accountId: string;
  site: string;
  title: string;
  url: string;
  kind: string;
  pill: LeakPill;
  seen: string;
  thumb: boolean;
  creator?: string;
};

export const thumbState = (sfwOn: boolean, previewsOn: boolean, revealed: boolean): ThumbState =>
  sfwOn || !previewsOn ? "placeholder" : revealed ? "clear" : "blurred";

const VERTICAL: Record<LeakPreview["vertical"], string> = { images: "Google Images", videos: "Google Videos" };

const at = (iso: string | undefined) => parseUtc(iso)?.getTime() ?? 0;

const newestSeen = (a: Leak, b: Leak) =>
  at(b.preview?.seen_at) - at(a.preview?.seen_at) || at(b.first_seen_at) - at(a.first_seen_at);

function tile(l: Leak, accountId: string, now: Date, tz: string): Tile {
  const p = l.preview;
  const day = p && dayLabel(p.seen_at, now, tz);
  return {
    key: `${accountId}:${l.leak_id}`,
    leakId: l.leak_id,
    accountId,
    site: l.leak_site,
    title: l.title || l.url,
    url: l.url,
    kind: l.kind,
    pill: l.pill,
    seen: p ? [`Seen in ${VERTICAL[p.vertical]}`, day].filter(Boolean).join(" · ") : seenNote(l, now, tz),
    thumb: p != null,
  };
}

export function previewTiles(leaks: Leak[], previewsOn: boolean, creatorId: string, now: Date, tz: string): Tile[] {
  const shown = previewsOn ? leaks.filter((l) => l.preview) : leaks.filter((l) => l.kind === "media");
  return [...shown].sort(newestSeen).map((l) => tile(l, l.account_id ?? creatorId, now, tz));
}

export function stripTiles(rows: Leak[], names: Record<string, string>, now: Date, tz: string): Tile[] {
  return rows
    .filter((l): l is Leak & { account_id: string } => l.preview != null && !!l.account_id && l.account_id in names)
    .sort(newestSeen)
    .slice(0, STRIP_MAX)
    .map((l) => ({ ...tile(l, l.account_id, now, tz), creator: names[l.account_id] }));
}

export const thumbSrc = (t: Pick<Tile, "accountId" | "leakId">, scopeAccountId: string | null) =>
  buildUrl(`/admin/leaks/watches/${encodeURIComponent(t.accountId)}/leaks/${encodeURIComponent(t.leakId)}/thumb`
    + (scopeAccountId ? `?account_id=${encodeURIComponent(scopeAccountId)}` : ""));

export type TilePhase = "first" | "waiting" | "retry" | "failed";
export type TileState = { revealed: boolean; phase: TilePhase };
export type TileAction = { type: "toggle" } | { type: "error" } | { type: "retry" };
export const TILE_START: TileState = { revealed: false, phase: "first" };

export function tileReducer(state: TileState, action: TileAction): TileState {
  if (state.phase === "failed") return state;
  if (action.type === "toggle") return { ...state, revealed: !state.revealed };
  if (action.type === "retry") return state.phase === "waiting" ? { ...state, phase: "retry" } : state;
  if (state.phase === "first") return { ...state, phase: "waiting" };
  return state.phase === "retry" ? { revealed: false, phase: "failed" } : state;
}

export type TileView =
  | { image: false; failed: boolean }
  | { image: true; blurred: boolean; pressed: boolean; label: "Unblur preview"; attempt: 0 | 1; hidden: boolean };

export function tileView(state: TileState, sfwOn: boolean, thumb: boolean): TileView {
  const s = thumbState(sfwOn, thumb, state.revealed);
  const failed = state.phase === "failed";
  if (s === "placeholder" || failed) return { image: false, failed: s !== "placeholder" && failed };
  const clear = s === "clear";
  return { image: true, blurred: !clear, pressed: clear, label: "Unblur preview",
    attempt: state.phase === "retry" ? 1 : 0, hidden: state.phase === "waiting" };
}
