import type { LeakPill } from "./leakView";

export type SceneKind = "google" | "google_images" | "mega" | "forum" | "x";
export type CueKind = SceneKind | "end";
export type Cue = { t_s: number; kind: CueKind };
export type OfferVideo = { duration_s: number; has_poster: boolean; cues: Cue[] | null };
export type SceneLeak = { leak_id: string; leak_site: string; kind: string; title: string; pill: LeakPill; preview: null };
export type Scenes = Record<SceneKind, SceneLeak[]>;
export type ActiveScene = { kind: CueKind; start: number; end: number | null };
export type SceneView =
  | { kind: "empty"; text: string }
  | { kind: "cards"; flipped: boolean; badge: string | null; cards: SceneLeak[] };

export const NONE_FOUND = "None found here";
export const PREVIEW_BADGE = "Preview · not removed";
export const NO_LONGER = "No longer available";
export const ILLUSTRATION = "Illustration";

export const SCENE_LABEL: Record<SceneKind, string> = {
  google: "Google",
  google_images: "Google Images",
  mega: "Mega",
  forum: "Forums",
  x: "X",
};

export function activeScene(cues: Cue[] | null, t: number): ActiveScene | null {
  if (!cues) return null;
  let at = -1;
  cues.forEach((c, i) => {
    if (c.t_s <= t) at = i;
  });
  if (at < 0) return null;
  return { kind: cues[at].kind, start: cues[at].t_s, end: cues[at + 1]?.t_s ?? null };
}

export function sceneView(scene: SceneLeak[], t: number, start: number, end: number | null): SceneView {
  if (!scene.length) return { kind: "empty", text: NONE_FOUND };
  const flipped = end !== null && t >= (start + end) / 2;
  return { kind: "cards", flipped, badge: flipped ? PREVIEW_BADGE : null, cards: scene };
}
