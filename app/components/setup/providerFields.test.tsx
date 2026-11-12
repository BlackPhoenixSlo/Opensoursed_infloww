import { describe, it, expect } from "vitest";
import { HELP, LABELS, wrongFieldWarning } from "./providerFields";

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
