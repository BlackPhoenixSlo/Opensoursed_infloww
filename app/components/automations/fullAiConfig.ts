/**
 * Full AI Chat's config shapes and the Settings controls' pure reads and edits (split out of `fullAiTestChat.ts`,
 * which keeps the Test chat reducer): the config types (`full_ai_config.DEFAULTS`, the GET body), key-order-free
 * compare, the JSON modal's "All settings" rows, and each control's value / patch plus the window header's config
 * line. Pure: `useFullAiConfig` does the requests, the components only render and dispatch.
 */

import { CASUAL_STYLE } from "@/lib/fullAiStyle";

/** The five human-texting layers (`full_ai_config.STYLE_LAYERS`), in the server's order. Kept here for the
 *  `StyleLayer` type; test_full_ai_config pins it to the server's. */
export const STYLE_LAYERS = ["texting", "nonnative", "spacing", "typos", "painful"] as const;
export type StyleLayer = (typeof STYLE_LAYERS)[number];
export type StyleLayers = Record<StyleLayer, boolean>;

/** One side of Full AI Chat's config (`full_ai_config.DEFAULTS` keys): draft, checkpoint or previous. The page edits the
 *  named keys, the JSON the rest; they are optional, as a hand-typed JSON draft may lack them until the server
 *  refuses it. */
export interface FullAiConfig {
  reply_speed?: string;
  /** The stored human-texting layers; `text_style` is only the legacy write alias (never stored). */
  style?: Partial<StyleLayers>;
  text_style?: string;
  /** Ordered: the first is the Writer, the rest its fallbacks. */
  writers?: string[];
  gifs?: boolean;
  sell_on?: boolean;
  /** PPV caption: "chat" (default) = the chat Writer's last bubble, "caption" = its own call. */
  caption_writer?: string;
  /** Content folders: `include: []` = all (ticket 49, `sellFoldersForm.ts`). */
  folders?: { include: string[]; exclude: string[] };
  /** Chance (%, 0-100) a reply gets one thumb-typo while Typos is on; null / absent = auto (~1 per 5 sentences). */
  typo_pct?: number | null;
  /** The Sell group's switches (`sellSwitches`), test + live (Shadow ignores); absent = on (server defaults).
   *  Unasked offers: the DRAFT Router questions count. */
  draft_questions?: boolean;
  /** Chat tease: in normal chat photos may ride her reply, free or Jev-priced. */
  chat_tease?: boolean;
  /** Implied asks: a vague ask counts as asking for content. */
  ask_implied?: boolean;
  /** Nearest piece: "off" | "plain" | "note". */
  sell_nearest?: string;
  /** Fill the set: "fill" | "shoot". */
  sell_bundle?: string;
  /** Spacing of unasked pieces. */
  sell_spacing?: boolean;
  /** He likes: what he likes steers what the AI sends. */
  he_likes?: boolean;
  /** JSON-only, test Mode: a fresh offer aims at the number of pieces he names (at most 5); absent = on. */
  sell_count?: boolean;
  /** JSON-only, every Mode: emojis stripped from her replies; off / absent = the account's strip-emojis setting. */
  strip_emojis?: boolean;
  /** Chance (%, 0-100) a Turn offers the GIF (sticker) block while GIFs is on; null / absent = auto (every eligible Turn). */
  gif_pct?: number | null;
  /** Live only, JSON-only: lifetime spend (cents) at which a Fan is left to humans; 0 = off ("Top spend limit"). */
  top_spend_cents?: number;
  /** Live only, JSON-only: the Fans list, OF fan-list ids; empty include = every Fan, exclude wins ("Fans"). */
  fans?: { include: number[]; exclude: number[] };
  [key: string]: unknown;
}
/** One key of the config GET's `reference` (`full_ai_config.reference`): its default, the values it accepts, what it
 *  does, and the Settings page control that edits it (null = JSON only). */
export interface SettingRef { key: string; default: unknown; allowed: string; about: string; page: string | null }
/** GET /admin/full-ai/config's body; every config write answers the same shape. */
export interface ConfigBody {
  checkpoint: FullAiConfig;
  previous: FullAiConfig | null;
  draft: FullAiConfig;
  rev: number;
  errors: string[];
  /** The models a `writers` entry may name (the Writer select's options). */
  writer_models?: string[];
  /** Every key the JSON takes, in `full_ai_config.DEFAULTS` order (the JSON modal's "All settings" table). */
  reference?: SettingRef[];
  /** The controls' server constants (`full_ai_config.limits`). */
  limits: ConfigLimits;
}
/** GET config's `limits`: the Writer chain's max length, the reply speeds and the one a config without the key runs on. */
export interface ConfigLimits { max_writers: number; reply_speeds: string[]; default_reply_speed: string }

/** Same config whatever the key order (the server's JSON may order a side's keys differently). */
function stable(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === "object") {
    return Object.fromEntries(Object.keys(v).sort().map((k) => [k, stable((v as Record<string, unknown>)[k])]));
  }
  return v;
}
export const sameConfig = (a: unknown, b: unknown) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));

/** One row of the JSON modal's "All settings" table: default and the side's value as compact JSON, `changed` when they
 *  differ (key order ignored), `where` the page control or "JSON". A key the side lacks reads as its default (the
 *  server fills it). */
export interface SettingRow { key: string; def: string; value: string; changed: boolean; allowed: string; about: string; where: string }
export function settingRows(reference: SettingRef[], side: FullAiConfig | null): SettingRow[] {
  return reference.map((r) => {
    const v = side && side[r.key] !== undefined ? side[r.key] : r.default;
    return { key: r.key, def: JSON.stringify(r.default), value: JSON.stringify(v), changed: !sameConfig(v, r.default),
      allowed: r.allowed, about: r.about, where: r.page ?? "JSON" };
  });
}

/** A reply speed's label (the speeds come from `limits.reply_speeds`); one without an entry shows as itself. */
const SPEED_LABEL: Record<string, string> = { "0-2m": "0-2 min" };
export const speedLabel = (speed: string) => SPEED_LABEL[speed] ?? speed;
const allLayers = (on: boolean) => Object.fromEntries(STYLE_LAYERS.map((k) => [k, on])) as StyleLayers;

/** The side's layers as the server reads them (`full_ai_config.style_layers`): a valid legacy `text_style` wins
 *  (formal = all off, girl = all on), then `style`; a side with neither reads all off. No config yet (null) reads
 *  DEFAULTS' all on. */
export function styleLayers(cfg: FullAiConfig | null): StyleLayers {
  if (!cfg) return allLayers(true);
  const ts = cfg.text_style;
  if (ts === CASUAL_STYLE || ts === "formal") return allLayers(ts === CASUAL_STYLE);
  const s = cfg.style;
  if (!s || typeof s !== "object") return allLayers(false);
  return Object.fromEntries(STYLE_LAYERS.map((k) => [k, s[k] === true])) as StyleLayers;
}

/** The Human style master switch: on / off when every layer agrees, mixed otherwise. */
export type HumanStyle = "on" | "off" | "mixed";
export function humanStyle(cfg: FullAiConfig | null): HumanStyle {
  const v = Object.values(styleLayers(cfg));
  return v.every(Boolean) ? "on" : v.some(Boolean) ? "mixed" : "off";
}
/** The layers that are off, in plain words ("typos, spacing"), for the mixed state's hint. */
const LAYER_WORD: Record<StyleLayer, string> = {
  texting: "texting style", nonnative: "non-native", spacing: "spacing", typos: "typos", painful: "painful texting",
};
export const layersOff = (cfg: FullAiConfig | null) =>
  STYLE_LAYERS.filter((k) => !styleLayers(cfg)[k]).map((k) => LAYER_WORD[k]).join(", ");

/** The master switch's edit: every layer on or off. */
export const humanStylePatch = (on: boolean): Partial<FullAiConfig> => ({ style: allLayers(on), text_style: undefined });
/** The Typos switch's edit: the typos layer alone. Both drop a legacy `text_style` (it would win over `style`). */
export const typosPatch = (cfg: FullAiConfig | null, on: boolean): Partial<FullAiConfig> =>
  ({ style: { ...styleLayers(cfg), typos: on }, text_style: undefined });

type PctKey = "typo_pct" | "gif_pct";
/** A side's stored percent: a whole 0-100, else null (auto). */
const pctOf = (cfg: FullAiConfig | null, key: PctKey): number | null => {
  const p = cfg?.[key];
  return typeof p === "number" && Number.isInteger(p) && p >= 0 && p <= 100 ? p : null;
};
/** A % box's edit: "" = auto (null), a whole 0-100 = that percent; anything else is refused (null patch). */
function pctPatch(key: PctKey, text: string): Partial<FullAiConfig> | null {
  const t = text.trim();
  if (t === "") return { [key]: null };
  if (!/^\d{1,3}$/.test(t)) return null;
  const n = Number(t);
  return n <= 100 ? { [key]: n } : null;
}
/** The side's Typos %. */
export const typoPct = (cfg: FullAiConfig | null) => pctOf(cfg, "typo_pct");
/** The Typos % box's edit. */
export const typoPctPatch = (text: string) => pctPatch("typo_pct", text);
/** The side's GIFs % (`gif_pct`). */
export const gifPct = (cfg: FullAiConfig | null) => pctOf(cfg, "gif_pct");
/** The GIFs % box's edit. */
export const gifPctPatch = (text: string) => pctPatch("gif_pct", text);

/** A switch in the Sell group (shown while Sell is on): its key, label, state and hint. */
export type SellSwitchKey = "draft_questions" | "chat_tease" | "ask_implied" | "sell_nearest" | "sell_bundle" | "sell_spacing" | "he_likes";
export interface SellSwitch { key: SellSwitchKey; label: string; checked: boolean; hint: string }

/** In page order: the value each switch stores on / off. Any stored value but `off` reads on (absent = on, as the
 *  server defaults). test_full_ai_config pins the string values to `full_ai_config.SELL_NEAREST` / `SELL_BUNDLE`. */
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
  { key: "sell_spacing", label: "Spacing", on: true, off: false,
    hint: "Unasked pieces wait for his lines since the last one and count the pieces this sitting. An ask always goes through." },
  { key: "he_likes", label: "He likes", on: true, off: false,
    hint: "What he says he likes is stored and steers what the AI sends." },
];
const NEAREST_PLAIN = "Plain: the AI sells the nearest piece with no story. Tap for off.";

/** The Sell group's switches, in page order. */
export function sellSwitches(cfg: FullAiConfig | null): SellSwitch[] {
  return SELL_SWITCHES.map(({ key, label, off, hint }) => ({
    key, label, checked: cfg?.[key] !== off,
    hint: key === "sell_nearest" && cfg?.sell_nearest === "plain" ? NEAREST_PLAIN : hint,
  }));
}

/** A Sell group switch's edit: its on or off value. */
export function sellSwitchPatch(key: SellSwitchKey, on: boolean): Partial<FullAiConfig> {
  const s = SELL_SWITCHES.find((x) => x.key === key)!;
  return { [key]: on ? s.on : s.off };
}

/** The Writer select's edit: `model` first, the others keep their order as fallbacks (a full list of `maxWriters`,
 *  `limits.max_writers`, drops its last). */
export function writerPatch(cfg: FullAiConfig | null, model: string, maxWriters: number): Partial<FullAiConfig> {
  const rest = (cfg?.writers ?? []).filter((w) => w !== model);
  return { writers: [model, ...rest].slice(0, maxWriters) };
}

/** The Writer checklist's tick: an unticked model joins the chain's end, a ticked one leaves it. Null when refused:
 *  the last Writer (the server needs 1) or a full chain (`maxWriters`, `limits.max_writers`). */
export function toggleWriterPatch(cfg: FullAiConfig | null, model: string, maxWriters: number): Partial<FullAiConfig> | null {
  const ws = cfg?.writers ?? [];
  if (ws.includes(model)) return ws.length > 1 ? { writers: ws.filter((w) => w !== model) } : null;
  return ws.length < maxWriters ? { writers: [...ws, model] } : null;
}

/** A side's Writer chain for its window header, in the order tried. */
export const writersLine = (cfg: FullAiConfig) => `Writers ${(cfg.writers ?? []).join(" → ") || "none"}`;

const onOff = (on: boolean) => (on ? "on" : "off");

/** A side's config for its window header: reply speed (`defaultSpeed`, `limits.default_reply_speed`, when the side
 *  lacks it), Human style (+ "Typos off" unless all off, "Typos N%" when set), GIFs (on / off, "GIFs N%" when on and set). */
export function configLine(cfg: FullAiConfig, defaultSpeed: string): string {
  const label = speedLabel(cfg.reply_speed ?? defaultSpeed);
  const hs = humanStyle(cfg);
  const on = styleLayers(cfg).typos, pct = typoPct(cfg);
  const typos = hs !== "off" && !on ? " · Typos off" : on && pct !== null ? ` · Typos ${pct}%` : "";
  const gp = gifPct(cfg), gifs = cfg.gifs === true && gp !== null ? `${gp}%` : onOff(cfg.gifs === true);
  return `Reply ${label} · Human style ${hs}${typos} · GIFs ${gifs} · Caption ${cfg.caption_writer ?? "chat"}`;
}
