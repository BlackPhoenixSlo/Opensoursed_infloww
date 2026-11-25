import { describe, expect, it } from "vitest";

import {
  configLine, gifPct, gifPctPatch, humanStyle, humanStylePatch, layersOff, styleLayers, toggleWriterPatch, typoPct,
  typoPctPatch, typosPatch, writerPatch, writersLine, type HumanStyle, type StyleLayers, type FullAiConfig,
  sellSwitches, sellSwitchPatch, type SellSwitchKey, settingRows, type SettingRef, draftDiff, draftDiffLine, chatSwitch, type ChatSwitchKey,
  topSpendDollars, topSpendPatch, infoQuestionsLabel, captionLabel,
} from "./fullAiConfig";

const CP = { version: 1, reply_speed: "0-2m", text_style: "girl", gifs: false, writers: ["euryale-v2.3"] };

describe("configLine (a window header's config)", () => {
  it.each<[string, FullAiConfig, string]>([
    ["checkpoint", CP, "Reply 0-2 min · Human style on · GIFs off · Caption chat"],
    ["slower, formal, GIFs on", { ...CP, reply_speed: "0-15-60", text_style: "formal", gifs: true }, "Reply 0-15-60 min · Human style off · GIFs on · Caption chat"],
    ["layers all on", { reply_speed: "0-2m", style: ON }, "Reply 0-2 min · Human style on · GIFs off · Caption chat"],
    ["typos off", { reply_speed: "0-2m", style: { ...ON, typos: false }, gifs: true }, "Reply 0-2 min · Human style mixed · Typos off · GIFs on · Caption chat"],
    ["spacing off, typos on", { style: { ...ON, spacing: false } }, "Reply 0-2 min · Human style mixed · GIFs off · Caption chat"],
    ["all off: no Typos chip", { style: OFF }, "Reply 0-2 min · Human style off · GIFs off · Caption chat"],
    ["separate caption", { ...CP, caption_writer: "caption" }, "Reply 0-2 min · Human style on · GIFs off · Caption caption"],
    ["typos 30%", { style: ON, typo_pct: 30 }, "Reply 0-2 min · Human style on · Typos 30% · GIFs off · Caption chat"],
    ["typos 0%", { style: ON, typo_pct: 0 }, "Reply 0-2 min · Human style on · Typos 0% · GIFs off · Caption chat"],
    ["typos off hides the %", { style: { ...ON, typos: false }, typo_pct: 30 }, "Reply 0-2 min · Human style mixed · Typos off · GIFs off · Caption chat"],
    ["auto %: no chip", { style: ON, typo_pct: null }, "Reply 0-2 min · Human style on · GIFs off · Caption chat"],
    ["gifs 25%", { style: ON, gifs: true, gif_pct: 25 }, "Reply 0-2 min · Human style on · GIFs 25% · Caption chat"],
    ["gifs 0%", { style: ON, gifs: true, gif_pct: 0 }, "Reply 0-2 min · Human style on · GIFs 0% · Caption chat"],
    ["gifs off hides the %", { style: ON, gifs: false, gif_pct: 25 }, "Reply 0-2 min · Human style on · GIFs off · Caption chat"],
    ["gifs auto %", { style: ON, gifs: true, gif_pct: null }, "Reply 0-2 min · Human style on · GIFs on · Caption chat"],
  ])("%s", (_n, cfg, want) => {
    expect(configLine(cfg, "0-2m")).toBe(want);
  });
});

const ON: StyleLayers = { texting: true, nonnative: true, spacing: true, typos: true, painful: true };
const OFF: StyleLayers = { texting: false, nonnative: false, spacing: false, typos: false, painful: false };

describe("styleLayers / humanStyle (the server's read: text_style wins, then style; neither = all off; no config = DEFAULTS' all on)", () => {
  it.each<[string, FullAiConfig | null, StyleLayers, HumanStyle, string]>([
    ["no config", null, ON, "on", ""],
    ["no style key reads all off, as the server (rwl-c F8)", { gifs: true }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["a style that is not an object reads all off", { style: true as unknown as StyleLayers }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["all on", { style: ON }, ON, "on", ""],
    ["all off", { style: OFF }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["typos off", { style: { ...ON, typos: false } }, { ...ON, typos: false }, "mixed", "typos"],
    ["two off", { style: { ...ON, spacing: false, typos: false } }, { ...ON, spacing: false, typos: false }, "mixed", "spacing, typos"],
    ["legacy formal", { text_style: "formal" }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["legacy formal wins over style", { text_style: "formal", style: ON }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["legacy casual", { ...CP }, ON, "on", ""],
    ["an unknown text_style falls to style", { text_style: "boy", style: { ...ON, typos: false } }, { ...ON, typos: false }, "mixed", "typos"],
    ["a missing layer reads off", { style: { texting: true } }, { ...OFF, texting: true }, "mixed", "non-native, spacing, typos, painful texting"],
  ])("%s", (_n, cfg, layers, hs, off) => {
    expect([styleLayers(cfg), humanStyle(cfg), layersOff(cfg)]).toEqual([layers, hs, off]);
  });
});

describe("humanStylePatch / typosPatch", () => {
  it.each<[string, FullAiConfig | null, Partial<FullAiConfig>, StyleLayers]>([
    ["master on from mixed", { style: { ...ON, typos: false } }, humanStylePatch(true), ON],
    ["master off from on", { style: ON }, humanStylePatch(false), OFF],
    ["typos off keeps the other layers", { style: { ...ON, spacing: false } }, typosPatch({ style: { ...ON, spacing: false } }, false), { ...ON, spacing: false, typos: false }],
    ["typos on from all off", { style: OFF }, typosPatch({ style: OFF }, true), { ...OFF, typos: true }],
    ["typos off on a legacy draft", { ...CP }, typosPatch({ ...CP }, false), { ...ON, typos: false }],
    ["master off on a legacy draft", { ...CP }, humanStylePatch(false), OFF],
  ])("%s", (_n, cfg, patch, want) => {
    const next = { ...cfg, ...patch };
    expect([next.style, styleLayers(next)]).toEqual([want, want]);
    expect(JSON.parse(JSON.stringify(patch))).toEqual({ style: want });
  });
});

describe("typoPct / typoPctPatch (the Typos % box: empty = auto, a whole 0-100, else refused)", () => {
  it.each<[string, string, Partial<FullAiConfig> | null]>([
    ["empty = auto", "", { typo_pct: null }],
    ["blank = auto", "  ", { typo_pct: null }],
    ["zero", "0", { typo_pct: 0 }],
    ["a percent", "35", { typo_pct: 35 }],
    ["trimmed", " 7 ", { typo_pct: 7 }],
    ["hundred", "100", { typo_pct: 100 }],
    ["over 100 refused", "101", null],
    ["negative refused", "-5", null],
    ["decimal refused", "2.5", null],
    ["text refused", "abc", null],
  ])("%s", (_n, text, want) => {
    expect(typoPctPatch(text)).toEqual(want);
  });
  it.each<[string, FullAiConfig | null, number | null]>([
    ["no config", null, null], ["absent", {}, null], ["null", { typo_pct: null }, null],
    ["set", { typo_pct: 40 }, 40], ["zero", { typo_pct: 0 }, 0], ["out of range reads auto", { typo_pct: 140 }, null],
  ])("typoPct %s", (_n, cfg, want) => {
    expect(typoPct(cfg)).toBe(want);
  });
});

describe("sellSwitches / sellSwitchPatch (the Sell group: eight switches, all on by default)", () => {
  const LABELS = ["Unasked offers", "Chat tease", "Implied asks", "Nearest piece", "Fill the set", "Match his count", "Spacing", "He likes"];
  const KEYS: SellSwitchKey[] = ["draft_questions", "chat_tease", "ask_implied", "sell_nearest", "sell_bundle", "sell_count", "sell_spacing", "he_likes"];
  const NEAREST = "Nothing matches his ask: the AI sells the nearest piece and plays his ask out as a story. Off: no PPV.";
  const checked = (cfg: FullAiConfig | null) => Object.fromEntries(sellSwitches(cfg).map((s) => [s.key, s.checked]));
  const allOn = Object.fromEntries(KEYS.map((k) => [k, true]));

  it("lists the eight in page order with their hints", () => {
    const got = sellSwitches({});
    expect(got.map((s) => [s.key, s.label])).toEqual(KEYS.map((k, i) => [k, LABELS[i]]));
    expect(got.map((s) => s.hint)).toEqual([
      "When he is clearly into it the AI may send a PPV he did not ask for, and answer haggling with a new offer.",
      "In normal chat the AI may add photos to its normal reply without a word about them: free, or locked at a price Jev picks from the JSON list.",
      "\"send me something fun\" counts as asking for content.",
      NEAREST,
      "A photo offer holds up to 5 photos, filled to 3 with others that match his ask. Off: only photos from the same shoot, up to 4.",
      "He names a number (\"bundle of 5 videos\"): the offer aims at it, at most 5. Fewer when there are fewer.",
      "Unasked pieces wait for his lines since the last one and count the pieces this sitting. An ask always goes through.",
      "What he says he likes is stored and steers what the AI sends.",
    ]);
  });

  it.each<[string, FullAiConfig | null, Partial<Record<SellSwitchKey, boolean>>]>([
    ["no config: all on", null, {}],
    ["defaults (keys absent): all on", {}, {}],
    ["stored on values", { draft_questions: true, chat_tease: true, ask_implied: true, sell_nearest: "note", sell_bundle: "fill",
      sell_count: true, sell_spacing: true, he_likes: true }, {}],
    ["draft_questions false", { draft_questions: false }, { draft_questions: false }],
    ["chat_tease false", { chat_tease: false }, { chat_tease: false }],
    ["ask_implied false", { ask_implied: false }, { ask_implied: false }],
    ["sell_nearest off", { sell_nearest: "off" }, { sell_nearest: false }],
    ["sell_nearest plain reads on", { sell_nearest: "plain" }, {}],
    ["sell_bundle shoot", { sell_bundle: "shoot" }, { sell_bundle: false }],
    ["sell_count false", { sell_count: false }, { sell_count: false }],
    ["sell_spacing false", { sell_spacing: false }, { sell_spacing: false }],
    ["he_likes false", { he_likes: false }, { he_likes: false }],
  ])("checked: %s", (_n, cfg, offs) => {
    expect(checked(cfg)).toEqual({ ...allOn, ...offs });
  });

  it.each<[string, string]>([["note", NEAREST], ["off", NEAREST], ["plain", "Plain: the AI sells the nearest piece with no story. Tap for off."]])(
    "Nearest piece hint with sell_nearest %s", (v, hint) => {
      expect(sellSwitches({ sell_nearest: v }).find((s) => s.key === "sell_nearest")!.hint).toBe(hint);
    });

  it.each<[SellSwitchKey, Partial<FullAiConfig>, Partial<FullAiConfig>]>([
    ["draft_questions", { draft_questions: true }, { draft_questions: false }],
    ["chat_tease", { chat_tease: true }, { chat_tease: false }],
    ["ask_implied", { ask_implied: true }, { ask_implied: false }],
    ["sell_nearest", { sell_nearest: "note" }, { sell_nearest: "off" }],
    ["sell_bundle", { sell_bundle: "fill" }, { sell_bundle: "shoot" }],
    ["sell_count", { sell_count: true }, { sell_count: false }],
    ["sell_spacing", { sell_spacing: true }, { sell_spacing: false }],
    ["he_likes", { he_likes: true }, { he_likes: false }],
  ])("sellSwitchPatch %s", (key, on, off) => {
    expect(sellSwitchPatch(key, true)).toEqual(on);
    expect(sellSwitchPatch(key, false)).toEqual(off);
  });
});

describe("chatSwitch (the plain top-level switches: a stored boolean, else the server default)", () => {
  it.each<[string, ChatSwitchKey, FullAiConfig | null, string, boolean]>([
    ["Sexting absent reads on", "sext_on", {}, "Sexting", true],
    ["Sexting off", "sext_on", { sext_on: false }, "Sexting", false],
    ["Lead-in absent reads on", "lead_in", null, "Lead-in questions", true],
    ["Lead-in off", "lead_in", { lead_in: false }, "Lead-in questions", false],
    ["Read his photos absent reads on", "describe_fan_photos", {}, "Read his photos", true],
    ["Read his photos off", "describe_fan_photos", { describe_fan_photos: false }, "Read his photos", false],
    ["Strip emojis absent reads off", "strip_emojis", {}, "Strip emojis", false],
    ["Strip emojis on", "strip_emojis", { strip_emojis: true }, "Strip emojis", true],
    ["a non-boolean reads the default", "sext_on", { sext_on: "no" as unknown as boolean }, "Sexting", true],
  ])("%s", (_n, key, cfg, label, checked) => {
    expect([chatSwitch(cfg, key).label, chatSwitch(cfg, key).checked]).toEqual([label, checked]);
  });
  it("names the paid call on Read his photos", () => {
    expect(chatSwitch(null, "describe_fan_photos").hint).toBe("The AI reads a photo he sends: one paid vision call per photo.");
  });
});

describe("topSpendDollars / topSpendPatch (the Top spend limit box: dollars on the page, cents stored, 0 = no limit)", () => {
  it.each<[string, string, Partial<FullAiConfig> | null]>([
    ["whole dollars", "1000", { top_spend_cents: 100000 }],
    ["zero = no limit", "0", { top_spend_cents: 0 }],
    ["cents", "10.29", { top_spend_cents: 1029 }],
    ["one decimal", " 2.5 ", { top_spend_cents: 250 }],
    ["empty refused", "", null],
    ["three decimals refused", "1.005", null],
    ["negative refused", "-5", null],
    ["text refused", "lots", null],
  ])("%s", (_n, text, want) => {
    expect(topSpendPatch(text)).toEqual(want);
  });
  it.each<[string, FullAiConfig | null, string]>([
    ["no config", null, ""], ["absent", {}, ""], ["default", { top_spend_cents: 100000 }, "1000"],
    ["off", { top_spend_cents: 0 }, "0"], ["cents", { top_spend_cents: 1029 }, "10.29"],
    ["negative reads empty", { top_spend_cents: -1 }, ""], ["fraction reads empty", { top_spend_cents: 1.5 }, ""],
  ])("topSpendDollars %s", (_n, cfg, want) => {
    expect(topSpendDollars(cfg)).toBe(want);
  });
});

describe("infoQuestionsLabel / captionLabel", () => {
  it("labels the server's values; an unknown one shows as itself", () => {
    expect(["pick", "list", "x"].map(infoQuestionsLabel)).toEqual(["Pick one", "Whole list", "x"]);
    expect(["chat", "caption", "y"].map(captionLabel)).toEqual(["Last bubble", "Own call", "y"]);
  });
});

describe("gifPct / gifPctPatch (the GIFs % box: empty = auto, a whole 0-100, else refused)", () => {
  it.each<[string, string, Partial<FullAiConfig> | null]>([
    ["empty = auto", "", { gif_pct: null }],
    ["zero", "0", { gif_pct: 0 }],
    ["a percent", " 25 ", { gif_pct: 25 }],
    ["hundred", "100", { gif_pct: 100 }],
    ["over 100 refused", "101", null],
    ["negative refused", "-1", null],
    ["decimal refused", "12.5", null],
    ["text refused", "lots", null],
  ])("%s", (_n, text, want) => {
    expect(gifPctPatch(text)).toEqual(want);
  });
  it.each<[string, FullAiConfig | null, number | null]>([
    ["no config", null, null], ["absent", {}, null], ["null", { gif_pct: null }, null],
    ["set", { gif_pct: 25 }, 25], ["zero", { gif_pct: 0 }, 0], ["out of range reads auto", { gif_pct: 101 }, null],
    ["not typo_pct", { typo_pct: 30 }, null],
  ])("gifPct %s", (_n, cfg, want) => {
    expect(gifPct(cfg)).toBe(want);
  });
});

describe("toggleWriterPatch (tick adds at the end, untick drops; the last one and a full chain refuse)", () => {
  it.each<[string, string[], string, string[] | null]>([
    ["adds at the end", ["a"], "b", ["a", "b"]],
    ["drops a ticked one", ["a", "b", "c"], "b", ["a", "c"]],
    ["drops the Writer, the next answers first", ["a", "b"], "a", ["b"]],
    ["keeps the last one", ["a"], "a", null],
    ["refuses a seventh", ["a", "b", "c", "d", "e", "f"], "g", null],
    ["drops from a full chain", ["a", "b", "c", "d", "e", "f"], "f", ["a", "b", "c", "d", "e"]],
  ])("%s", (_n, writers, model, want) => {
    expect(toggleWriterPatch({ writers }, model, 6)).toEqual(want === null ? null : { writers: want });
  });
  it("the cap is the server's `limits.max_writers`, not a page constant", () => {
    expect(toggleWriterPatch({ writers: ["a", "b"] }, "c", 2)).toBeNull();
    expect(writerPatch({ writers: ["a", "b"] }, "c", 2)).toEqual({ writers: ["c", "a"] });
  });
  it("writersLine prints the chain in order", () => {
    expect(writersLine({ writers: ["a", "b"] })).toBe("Writers a → b");
    expect(writersLine({})).toBe("Writers none");
  });
});

describe("writerPatch (picked model first, the rest keep their order)", () => {
  const W = ["euryale-v2.3", "hermes-4-405b", "glm-5.3-flash", "deepseek-v4-flash"];
  it.each<[string, string[] | undefined, string, string[]]>([
    ["a fallback moves to the front", W, "glm-5.3-flash", ["glm-5.3-flash", "euryale-v2.3", "hermes-4-405b", "deepseek-v4-flash"]],
    ["the current Writer: unchanged", W, "euryale-v2.3", W],
    ["a new model on a full list drops the last", [...W, "euryale-v2.2", "deepseek-v4-pro"], "qwen-x",
      ["qwen-x", "euryale-v2.3", "hermes-4-405b", "glm-5.3-flash", "deepseek-v4-flash", "euryale-v2.2"]],
    ["a new model on a four-long list joins it", W, "deepseek-v4-pro", ["deepseek-v4-pro", ...W]],
    ["a new model on a short list joins it", ["hermes-4-405b"], "euryale-v2.3", ["euryale-v2.3", "hermes-4-405b"]],
    ["no writers yet", undefined, "euryale-v2.3", ["euryale-v2.3"]],
  ])("%s", (_n, writers, model, want) => {
    expect(writerPatch(writers ? { writers } : {}, model, 6)).toEqual({ writers: want });
  });
});

describe("settingRows: the JSON modal's All settings table", () => {
  const REF: SettingRef[] = [
    { key: "gifs", default: false, allowed: "true | false", about: "Sticker GIFs.", page: "GIFs" },
    { key: "style", default: { texting: true, typos: true }, allowed: "{texting, typos}", about: "Layers.", page: "Human style / Typos" },
    { key: "typo_pct", default: null, allowed: "whole 0-100, or null", about: "Typos %.", page: "Typos %" },
    { key: "writers", default: ["a", "b"], allowed: "1-6 ids", about: "Chain.", page: "Writers" },
    { key: "sext_on", default: true, allowed: "true | false", about: "Sexting.", page: null },
  ];
  const at = (live: FullAiConfig | null, draft: FullAiConfig | null, key: string) =>
    settingRows(REF, live, draft).find((r) => r.key === key)!;
  it.each<[string, FullAiConfig | null, FullAiConfig | null, string, string, string, boolean]>([
    ["bool same both sides, at default", { gifs: false }, { gifs: false }, "gifs", "false", "false", false],
    ["bool, draft differs from Live", { gifs: false }, { gifs: true }, "gifs", "false", "true", true],
    ["draft off default but = Live: not changed", { gifs: true }, { gifs: true }, "gifs", "true", "true", false],
    ["object, other key order = same", { style: { texting: true, typos: true } }, { style: { typos: true, texting: true } },
      "style", '{"texting":true,"typos":true}', '{"typos":true,"texting":true}', false],
    ["object, one layer off in draft", {}, { style: { texting: true, typos: false } },
      "style", '{"texting":true,"typos":true}', '{"texting":true,"typos":false}', true],
    ["null kept", { typo_pct: null }, { typo_pct: null }, "typo_pct", "null", "null", false],
    ["null Live, draft set", { typo_pct: null }, { typo_pct: 30 }, "typo_pct", "null", "30", true],
    ["list reordered = changed", { writers: ["a", "b"] }, { writers: ["b", "a"] }, "writers", '["a","b"]', '["b","a"]', true],
    ["key missing both reads as default", {}, {}, "sext_on", "true", "true", false],
    ["key missing in draft vs Live off", { sext_on: false }, {}, "sext_on", "false", "true", true],
    ["nothing read yet reads as default", null, null, "writers", '["a","b"]', '["a","b"]', false],
  ])("%s", (_n, live, draft, key, liveCell, value, changed) => {
    const r = at(live, draft, key);
    expect([r.live, r.value, r.changed]).toEqual([liveCell, value, changed]);
  });
  it("keeps the reference order, compact default JSON, allowed / about, and where = page control or JSON", () => {
    const rows = settingRows(REF, { gifs: true }, { gifs: true });
    expect(rows.map((r) => r.key)).toEqual(REF.map((r) => r.key));
    expect(rows.map((r) => r.where)).toEqual(["GIFs", "Human style / Typos", "Typos %", "Writers", "JSON"]);
    expect(rows[1]).toMatchObject({ def: '{"texting":true,"typos":true}', allowed: "{texting, typos}", about: "Layers." });
    expect(settingRows([], { gifs: true }, { gifs: true })).toEqual([]);
  });
});

describe("draftDiff / draftDiffLine: the status line under Make draft live", () => {
  const ORDER = ["reply_speed", "gifs", "style", "writers"];
  it.each<[string, FullAiConfig, FullAiConfig, string[]]>([
    ["same", { gifs: true, writers: ["a"] }, { writers: ["a"], gifs: true }, []],
    ["nested key order ignored", { style: { texting: true, typos: false } }, { style: { typos: false, texting: true } }, []],
    ["one key", { gifs: false }, { gifs: true }, ["gifs"]],
    ["reference order, not side order", { writers: ["a"], gifs: false }, { writers: ["b"], gifs: true }, ["gifs", "writers"]],
    ["key only in one side, after the reference keys", { gifs: true }, { gifs: true, zzz: 1, reply_speed: "x" }, ["reply_speed", "zzz"]],
    ["list order counts", { writers: ["a", "b"] }, { writers: ["b", "a"] }, ["writers"]],
  ])("%s", (_n, live, draft, keys) => {
    expect(draftDiff(live, draft, ORDER)).toEqual(keys);
  });

  const many = (n: number) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`k${i + 1}`, i]));
  it.each<[string, FullAiConfig | null, FullAiConfig | null, ReturnType<typeof draftDiffLine>]>([
    ["no checkpoint yet", null, { gifs: true }, null],
    ["no draft yet", { gifs: true }, null, null],
    ["equal", { gifs: true }, { gifs: true },
      { text: "Draft matches the saved Live settings.", differs: false }],
    ["two keys", { gifs: false, writers: ["a"] }, { gifs: true, writers: ["b"] },
      { text: "Draft differs from the Live settings in 2: gifs, writers. The Live settings stay until you tap Make draft live.",
        differs: true }],
    ["six keys: no +more", {}, many(6),
      { text: "Draft differs from the Live settings in 6: k1, k2, k3, k4, k5, k6. The Live settings stay until you tap Make draft live.",
        differs: true }],
    ["nine keys: first six, +3 more", {}, many(9),
      { text: "Draft differs from the Live settings in 9: k1, k2, k3, k4, k5, k6, +3 more. The Live settings stay until you tap Make draft live.",
        differs: true }],
  ])("%s", (_n, live, draft, line) => {
    expect(draftDiffLine(live, draft, ORDER)).toEqual(line);
  });
});
