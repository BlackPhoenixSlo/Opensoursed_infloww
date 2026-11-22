import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { HELP, KEY_URLS, LABELS, clearConfirm, keyUrl, wrongFieldWarning } from "./providerFields";

/**
 * Pins the one paste mistake this card can make silently: a DeepSeek key
 * (`sk-` + 32 hex) dropped into the DeepInfra or Z.ai box stores fine and only
 * shows up later as 401s from that provider.
 */
describe("wrongFieldWarning", () => {
  const DEEPSEEK = "sk-" + "a".repeat(32);

  it("flags a DeepSeek-shaped key in another provider's field", () => {
    expect(wrongFieldWarning("deepinfra", DEEPSEEK)).toMatch(/DeepSeek/);
    expect(wrongFieldWarning("zai", DEEPSEEK)).toMatch(/DeepSeek/);
    expect(wrongFieldWarning("anthropic", DEEPSEEK)).toMatch(/DeepSeek/);
  });

  it("never flags the DeepSeek field itself", () => {
    expect(wrongFieldWarning("deepseek", DEEPSEEK)).toBeNull();
  });

  it("stays quiet on an empty or whitespace field", () => {
    expect(wrongFieldWarning("deepinfra", "")).toBeNull();
    expect(wrongFieldWarning("deepinfra", "   ")).toBeNull();
  });

  it("does not flag a key that is merely sk-prefixed but a different shape", () => {
    expect(wrongFieldWarning("deepinfra", "sk-short")).toBeNull();
    expect(wrongFieldWarning("deepinfra", "di-" + "b".repeat(32))).toBeNull();
  });

  it("flags an Anthropic key (sk-ant-) outside the Anthropic field", () => {
    const ANT = "sk-ant-api03-" + "x".repeat(20);
    expect(wrongFieldWarning("deepseek", ANT)).toMatch(/Anthropic/);
    expect(wrongFieldWarning("zai", "sk-ant-usr-" + "y".repeat(20))).toMatch(/Anthropic/);
    expect(wrongFieldWarning("anthropic", ANT)).toBeNull();
  });
});

describe("anthropic provider copy", () => {
  it("has a label and help text naming Claude Opus and the console", () => {
    expect(LABELS.anthropic).toMatch(/Anthropic/);
    expect(HELP.anthropic).toMatch(/Claude Opus/);
    expect(HELP.anthropic).toMatch(/console\.anthropic\.com/);
  });
});

describe("typesafe provider copy", () => {
  it("has a label and help text saying the server key is the fallback", () => {
    expect(LABELS.typesafe).toMatch(/TypeSafe/);
    expect(HELP.typesafe).toMatch(/server's key/);
  });
});

describe("clearConfirm", () => {
  it("says a cleared TypeSafe key falls back to the server's, which pays", () => {
    const own = clearConfirm("typesafe");
    expect(own).toMatch(/^Remove your TypeSafe \(Jev\) API key\?/);
    expect(own).toMatch(/server's key and the server pays/);
    expect(own).not.toMatch(/stop replying/);
    expect(clearConfirm("typesafe", "ann")).toMatch(/^Remove @ann's TypeSafe/);
  });
  it("names other providers by label on both forms", () => {
    expect(clearConfirm("deepinfra")).toBe("Remove your DeepInfra API key? Your models stop replying until you add one.");
    expect(clearConfirm("deepinfra", "ann")).toBe("Remove @ann's DeepInfra API key? Their models stop replying until one is added.");
    expect(clearConfirm("newvendor")).toMatch(/^Remove your newvendor\?/);
  });
});

describe("Full AI Chat Writer host copy", () => {
  it("labels NanoGPT and names its Writer and site", () => {
    expect(LABELS.nanogpt).toMatch(/NanoGPT/);
    expect(HELP.nanogpt).toMatch(/Full AI Chat/);
    expect(HELP.nanogpt).toMatch(/Euryale/);
    expect(HELP.nanogpt).toMatch(/nano-gpt\.com/);
  });

  it("labels OpenRouter and names its Writer and site", () => {
    expect(LABELS.openrouter).toMatch(/OpenRouter/);
    expect(HELP.openrouter).toMatch(/Full AI Chat/);
    expect(HELP.openrouter).toMatch(/Hermes/);
    expect(HELP.openrouter).toMatch(/openrouter\.ai/);
  });
});

describe("keyUrl", () => {
  it("links every provider with a label to an https key page", () => {
    for (const id of Object.keys(LABELS)) expect(keyUrl(id)).toMatch(/^https:\/\//);
  });
  it("maps server key names to their vendor page", () => {
    expect(keyUrl("DEEPSEEK_API_KEY")).toBe(KEY_URLS.deepseek);
    expect(keyUrl("HELP_ASSISTANT_ANTHROPIC_KEY")).toBe(KEY_URLS.anthropic);
    expect(keyUrl("GOOGLE_DRIVE_API_KEY")).toBe(KEY_URLS.google);
  });
  it("links every vendor key in the server's secrets_store KNOWN (read from the source, no hand copy)", () => {
    const src = readFileSync(resolve(__dirname, "..", "..", "..", "service", "secrets_store.py"), "utf8");
    const known = [...src.matchAll(/^ {4}"([A-Z][A-Z0-9_]*)": \{/gm)].map((m) => m[1]);
    expect(known).toContain("TYPESAFE_API_KEY");
    const vendorless = new Set(["ADMIN_PASSWORD", "SHARE_TOKEN"]);
    for (const k of known) {
      if (vendorless.has(k)) continue;
      expect(keyUrl(k), k).toMatch(/^https:\/\//);
    }
  });
  it("points TypeSafe at its keys page (docs.typesafe.ai/quickstart)", () => {
    expect(KEY_URLS.typesafe).toBe("https://console.typesafe.ai/keys");
  });
  it("has no link for vendorless keys", () => {
    expect(keyUrl("ADMIN_PASSWORD")).toBeNull();
    expect(keyUrl("SHARE_TOKEN")).toBeNull();
  });
});
