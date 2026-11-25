const STATES = ["bare", "sexy_covered", "normal_covered", "sheer_covered", "hidden_not_worn", "not_visible"] as const;
const YN = ["y", "n"] as const;

export const JEV_OPTIONS = {
  lane: ["free", "$10", "$50", "$100"],
  breasts: STATES,
  crotch: STATES,
  butt: STATES,
  outfit: ["nude", "topless_with_bottoms", "lingerie_or_bodysuit", "swimwear", "everyday_clothes", "sheet_or_towel"],
  toy: ["no_toy", "toy_visible_not_in_use", "toy_touching_or_inserted"],
  people_count: ["one", "two_or_more", "none"],
  pose: ["standing", "sitting", "kneeling", "lying_on_back", "lying_on_stomach", "lying_on_side",
    "all_fours_or_bent_over", "close_up_no_pose"],
  framing: ["face_close_up", "face_and_chest", "upper_body", "most_of_body", "full_body", "body_part_close_up",
    "body_no_face"],
  face_visible: ["full_face", "partial_face", "no_face"],
  setting: ["bedroom", "bathroom", "living_room", "kitchen", "outdoors", "car", "gym", "other"],
  added_text: ["caption_text", "emoji_or_sticker_only", "nothing_added"],
  feet_detail: ["not_in_picture", "bare", "socks", "stockings_fishnets_nylons", "heels", "other_shoes"],
  penetration: YN,
  censor_edit: YN,
  watermark: YN,
  see_through: YN,
  topless: YN,
  self_touch: YN,
  legs_spread: YN,
  mirror_selfie: YN,
  multi_panel: YN,
  breasts_focus: YN,
  butt_focus: YN,
  crotch_focus: YN,
  feet_focus: YN,
  soles_visible: YN,
  bare_toes_visible: YN,
  wears_heels: YN,
  wears_stockings_or_fishnets: YN,
  wears_socks: YN,
  feet_in_water: YN,
} as const satisfies Record<string, readonly string[]>;

export type JevKey = keyof typeof JEV_OPTIONS;
export const JEV_KEYS = Object.keys(JEV_OPTIONS) as JevKey[];
export type JevPicks = Partial<Record<JevKey, string>>;

export const JEV_CONTENT: readonly JevKey[] = ["lane", "breasts", "crotch", "butt", "outfit", "toy", "people_count"];
export const JEV_DETAILS: readonly JevKey[] = ["pose", "framing", "face_visible", "setting", "added_text",
  "penetration", "censor_edit", "watermark", "see_through", "topless", "self_touch", "legs_spread", "mirror_selfie",
  "multi_panel"];
export const JEV_FOCUS: readonly JevKey[] = ["breasts_focus", "butt_focus", "crotch_focus"];
export const JEV_FEET: readonly JevKey[] = ["feet_detail", "feet_focus", "soles_visible", "bare_toes_visible",
  "wears_heels", "wears_stockings_or_fishnets", "wears_socks", "feet_in_water"];

export const isJevKey = (k: string): k is JevKey => Object.prototype.hasOwnProperty.call(JEV_OPTIONS, k);

export function picksFromAi(ai: Record<string, unknown>): JevPicks {
  const raw = ai.jev_picks;
  const out: JevPicks = {};
  if (!raw || typeof raw !== "object") return out;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (isJevKey(k) && typeof v === "string" && (JEV_OPTIONS[k] as readonly string[]).includes(v)) out[k] = v;
  }
  return out;
}

export function aiValue(ai: Record<string, unknown>, key: JevKey): string | null {
  const reading = ai.jev_ai;
  const v = reading && typeof reading === "object" ? (reading as Record<string, unknown>)[key] : undefined;
  return typeof v === "string" ? v : null;
}

const YN_WORD: Record<string, string> = { y: "yes", n: "no" };
export const optionLabel = (v: string) => YN_WORD[v] ?? v.replace(/_/g, " ");

export function unsetLabel(key: JevKey, ai: string | null): string {
  const prefix = key === "lane" ? "auto" : "AI";
  if (ai !== null) return `${prefix}: ${optionLabel(ai)}`;
  if ((JEV_FEET as readonly string[]).includes(key)) return "None";
  return key === "lane" ? "auto" : "—";
}
