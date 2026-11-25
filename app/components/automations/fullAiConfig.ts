import { CASUAL_STYLE } from "@/lib/fullAiStyle";

export const STYLE_LAYERS = ["texting", "nonnative", "spacing", "typos", "painful"] as const;
export type StyleLayer = (typeof STYLE_LAYERS)[number];
export type StyleLayers = Record<StyleLayer, boolean>;

export interface FullAiConfig {
  reply_speed?: string;
  style?: Partial<StyleLayers>;
  text_style?: string;
  writers?: string[];
  gifs?: boolean;
  sell_on?: boolean;
  sext_on?: boolean;
  lead_in?: boolean;
  describe_fan_photos?: boolean;
  info_questions?: string;
  caption_writer?: string;
  folders?: { include: string[]; exclude: string[] };
  typo_pct?: number | null;
  draft_questions?: boolean;
  /** Chat tease: in normal chat photos may ride her reply, free or Jev-priced. */
  chat_tease?: boolean;
  ask_implied?: boolean;
  sell_nearest?: string;
  sell_bundle?: string;
  sell_spacing?: boolean;
  he_likes?: boolean;
  sell_count?: boolean;
  strip_emojis?: boolean;
  gif_pct?: number | null;
  top_spend_cents?: number;
  /** Fans, live only: OF fan-list ids; empty include = every Fan, exclude wins (`fansForm.ts`). */
  fans?: { include: number[]; exclude: number[] };
  [key: string]: unknown;
}
export interface SettingRef { key: string; default: unknown; allowed: string; about: string; page: string | null }
export interface ConfigBody {
  checkpoint: FullAiConfig;
  previous: FullAiConfig | null;
  draft: FullAiConfig;
  rev: number;
  errors: string[];
  writer_models?: string[];
  writer_providers?: Record<string, string>;
  provider_labels?: Record<string, string>;
  owner_keys?: Record<string, { set: boolean }> | null;
  reference?: SettingRef[];
  limits: ConfigLimits;
}
export interface ConfigLimits {
  max_writers: number; reply_speeds: string[]; default_reply_speed: string;
  info_questions: string[]; caption_writers: string[];
}

function stable(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === "object") {
    return Object.fromEntries(Object.keys(v).sort().map((k) => [k, stable((v as Record<string, unknown>)[k])]));
  }
  return v;
}
export const sameConfig = (a: unknown, b: unknown) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));

export interface SettingRow {
  key: string; def: string; live: string; value: string; changed: boolean; allowed: string; about: string; where: string;
}
export function settingRows(reference: SettingRef[], live: FullAiConfig | null, draft: FullAiConfig | null): SettingRow[] {
  return reference.map((r) => {
    const of = (side: FullAiConfig | null) => (side && side[r.key] !== undefined ? side[r.key] : r.default);
    const l = of(live), v = of(draft);
    return { key: r.key, def: JSON.stringify(r.default), live: JSON.stringify(l), value: JSON.stringify(v),
      changed: !sameConfig(v, l), allowed: r.allowed, about: r.about, where: r.page ?? "JSON" };
  });
}

export function draftDiff(checkpoint: FullAiConfig, draft: FullAiConfig, order: string[] = []): string[] {
  const keys = [...new Set([...order, ...Object.keys(checkpoint), ...Object.keys(draft)])];
  return keys.filter((k) => !sameConfig(checkpoint[k], draft[k]));
}

/** The settings column's status line under Make draft live: null while either side is not read yet. */
export function draftDiffLine(checkpoint: FullAiConfig | null, draft: FullAiConfig | null, order: string[] = []):
  { text: string; differs: boolean } | null {
  if (!checkpoint || !draft) return null;
  const keys = draftDiff(checkpoint, draft, order);
  if (keys.length === 0) return { text: "Draft matches the saved Live settings.", differs: false };
  const shown = keys.slice(0, 6).join(", ") + (keys.length > 6 ? `, +${keys.length - 6} more` : "");
  return {
    text: `Draft differs from the Live settings in ${keys.length}: ${shown}. The Live settings stay until you tap Make draft live.`,
    differs: true,
  };
}

/** A reply speed's label (the speeds come from `limits.reply_speeds`); one without an entry shows as itself. */
const SPEED_LABEL: Record<string, string> = { "0-2m": "0-2 min", "0-15-60": "0-15-60 min" };
export const speedLabel = (speed: string) => SPEED_LABEL[speed] ?? speed;
const INFO_QUESTIONS_LABEL: Record<string, string> = { pick: "Pick one", list: "Whole list" };
const CAPTION_LABEL: Record<string, string> = { chat: "Last bubble", caption: "Own call" };
export const infoQuestionsLabel = (v: string) => INFO_QUESTIONS_LABEL[v] ?? v;
export const captionLabel = (v: string) => CAPTION_LABEL[v] ?? v;
const allLayers = (on: boolean) => Object.fromEntries(STYLE_LAYERS.map((k) => [k, on])) as StyleLayers;

export function styleLayers(cfg: FullAiConfig | null): StyleLayers {
  if (!cfg) return allLayers(true);
  const ts = cfg.text_style;
  if (ts === CASUAL_STYLE || ts === "formal") return allLayers(ts === CASUAL_STYLE);
  const s = cfg.style;
  if (!s || typeof s !== "object") return allLayers(false);
  return Object.fromEntries(STYLE_LAYERS.map((k) => [k, s[k] === true])) as StyleLayers;
}

export type HumanStyle = "on" | "off" | "mixed";
export function humanStyle(cfg: FullAiConfig | null): HumanStyle {
  const v = Object.values(styleLayers(cfg));
  return v.every(Boolean) ? "on" : v.some(Boolean) ? "mixed" : "off";
}
const LAYER_WORD: Record<StyleLayer, string> = {
  texting: "texting style", nonnative: "non-native", spacing: "spacing", typos: "typos", painful: "painful texting",
};
export const layersOff = (cfg: FullAiConfig | null) =>
  STYLE_LAYERS.filter((k) => !styleLayers(cfg)[k]).map((k) => LAYER_WORD[k]).join(", ");

// Drop legacy text_style: it would win over style.
export const humanStylePatch = (on: boolean): Partial<FullAiConfig> => ({ style: allLayers(on), text_style: undefined });
export const typosPatch = (cfg: FullAiConfig | null, on: boolean): Partial<FullAiConfig> =>
  ({ style: { ...styleLayers(cfg), typos: on }, text_style: undefined });

type PctKey = "typo_pct" | "gif_pct";
const pctOf = (cfg: FullAiConfig | null, key: PctKey): number | null => {
  const p = cfg?.[key];
  return typeof p === "number" && Number.isInteger(p) && p >= 0 && p <= 100 ? p : null;
};
function pctPatch(key: PctKey, text: string): Partial<FullAiConfig> | null {
  const t = text.trim();
  if (t === "") return { [key]: null };
  if (!/^\d{1,3}$/.test(t)) return null;
  const n = Number(t);
  return n <= 100 ? { [key]: n } : null;
}
export const typoPct = (cfg: FullAiConfig | null) => pctOf(cfg, "typo_pct");
export const typoPctPatch = (text: string) => pctPatch("typo_pct", text);
export const gifPct = (cfg: FullAiConfig | null) => pctOf(cfg, "gif_pct");
export const gifPctPatch = (text: string) => pctPatch("gif_pct", text);

export type SellSwitchKey =
  | "draft_questions" | "chat_tease" | "ask_implied" | "sell_nearest" | "sell_bundle" | "sell_count" | "sell_spacing" | "he_likes";
export interface SellSwitch { key: SellSwitchKey; label: string; checked: boolean; hint: string }

const SELL_SWITCHES: { key: SellSwitchKey; label: string; on: boolean | string; off: boolean | string; hint: string }[] = [
  { key: "draft_questions", label: "Unasked offers", on: true, off: false,
    hint: "When he is clearly into it the AI may send a PPV he did not ask for, and answer haggling with a new offer." },
  { key: "chat_tease", label: "Chat tease", on: true, off: false,
    hint: "In normal chat the AI may add photos to its normal reply without a word about them: free, or locked at a price Jev "
      + "picks from the JSON list." },
  { key: "ask_implied", label: "Implied asks", on: true, off: false,
    hint: "\"send me something fun\" counts as asking for content." },
  { key: "sell_nearest", label: "Nearest piece", on: "note", off: "off",
    hint: "Nothing matches his ask: the AI sells the nearest piece and plays his ask out as a story. Off: no PPV." },
  { key: "sell_bundle", label: "Fill the set", on: "fill", off: "shoot",
    hint: "A photo offer holds up to 5 photos, filled to 3 with others that match his ask. Off: only photos from the same "
      + "shoot, up to 4." },
  { key: "sell_count", label: "Match his count", on: true, off: false,
    hint: "He names a number (\"bundle of 5 videos\"): the offer aims at it, at most 5. Fewer when there are fewer." },
  { key: "sell_spacing", label: "Spacing", on: true, off: false,
    hint: "Unasked pieces wait for his lines since the last one and count the pieces this sitting. An ask always goes through." },
  { key: "he_likes", label: "He likes", on: true, off: false,
    hint: "What he says he likes is stored and steers what the AI sends." },
];
const NEAREST_PLAIN = "Plain: the AI sells the nearest piece with no story. Tap for off.";

export function sellSwitches(cfg: FullAiConfig | null): SellSwitch[] {
  return SELL_SWITCHES.map(({ key, label, off, hint }) => ({
    key, label, checked: cfg?.[key] !== off,
    hint: key === "sell_nearest" && cfg?.sell_nearest === "plain" ? NEAREST_PLAIN : hint,
  }));
}

export function sellSwitchPatch(key: SellSwitchKey, on: boolean): Partial<FullAiConfig> {
  const s = SELL_SWITCHES.find((x) => x.key === key)!;
  return { [key]: on ? s.on : s.off };
}

export type ChatSwitchKey = "sext_on" | "lead_in" | "describe_fan_photos" | "strip_emojis";
const CHAT_SWITCHES: Record<ChatSwitchKey, { label: string; def: boolean; hint: string }> = {
  sext_on: { label: "Sexting", def: true, hint: "Off: normal chat only." },
  lead_in: { label: "Lead-in questions", def: true,
    hint: "Get-to-know asks are led into, not asked straight. Test chat + live." },
  describe_fan_photos: { label: "Read his photos", def: true, hint: "The AI reads a photo he sends: one paid vision call per photo." },
  strip_emojis: { label: "Strip emojis", def: false, hint: "No emojis in the AI's replies. Off: the account's own strip-emojis setting decides." },
};
export function chatSwitch(cfg: FullAiConfig | null, key: ChatSwitchKey): { label: string; hint: string; checked: boolean } {
  const { label, def, hint } = CHAT_SWITCHES[key];
  const v = cfg?.[key];
  return { label, hint, checked: typeof v === "boolean" ? v : def };
}

export function topSpendDollars(cfg: FullAiConfig | null): string {
  const c = cfg?.top_spend_cents;
  return typeof c === "number" && Number.isInteger(c) && c >= 0 ? String(c / 100) : "";
}
export function topSpendPatch(text: string): Partial<FullAiConfig> | null {
  const t = text.trim();
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(t)) return null;
  return { top_spend_cents: Math.round(Number(t) * 100) };
}

export function writerPatch(cfg: FullAiConfig | null, model: string, maxWriters: number): Partial<FullAiConfig> {
  const rest = (cfg?.writers ?? []).filter((w) => w !== model);
  return { writers: [model, ...rest].slice(0, maxWriters) };
}

export function toggleWriterPatch(cfg: FullAiConfig | null, model: string, maxWriters: number): Partial<FullAiConfig> | null {
  const ws = cfg?.writers ?? [];
  if (ws.includes(model)) return ws.length > 1 ? { writers: ws.filter((w) => w !== model) } : null;
  return ws.length < maxWriters ? { writers: [...ws, model] } : null;
}

export const writersLine = (cfg: FullAiConfig) => `Writers ${(cfg.writers ?? []).join(" → ") || "none"}`;

const onOff = (on: boolean) => (on ? "on" : "off");

export function configLine(cfg: FullAiConfig, defaultSpeed: string): string {
  const label = speedLabel(cfg.reply_speed ?? defaultSpeed);
  const hs = humanStyle(cfg);
  const on = styleLayers(cfg).typos, pct = typoPct(cfg);
  const typos = hs !== "off" && !on ? " · Typos off" : on && pct !== null ? ` · Typos ${pct}%` : "";
  const gp = gifPct(cfg), gifs = cfg.gifs === true && gp !== null ? `${gp}%` : onOff(cfg.gifs === true);
  return `Reply ${label} · Human style ${hs}${typos} · GIFs ${gifs} · Caption ${cfg.caption_writer ?? "chat"}`;
}
