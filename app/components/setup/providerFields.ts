export const LABELS: Record<string, string> = {
  deepseek: "DeepSeek API key",
  deepinfra: "DeepInfra API key",
  zai: "Z.ai (GLM) API key",
  anthropic: "Anthropic (Claude) API key",
  typesafe: "TypeSafe (Jev) API key",
  nanogpt: "NanoGPT API key",
  openrouter: "OpenRouter API key",
};

// Warning only, never a block: a wrong key shape pasted here stores fine and 401s silently later.
const DEEPSEEK_SHAPE = /^sk-[0-9a-f]{32}$/i;
const ANTHROPIC_SHAPE = /^sk-ant-/;

export function wrongFieldWarning(provider: string, value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  if (provider !== "deepseek" && DEEPSEEK_SHAPE.test(v)) {
    return "That looks like a DeepSeek key — it belongs in the DeepSeek field below.";
  }
  if (provider !== "anthropic" && ANTHROPIC_SHAPE.test(v)) {
    return "That looks like an Anthropic key — it belongs in the Anthropic field below.";
  }
  return null;
}

export const HELP: Record<string, string> = {
  deepseek: "Powers chat replies and most automations. platform.deepseek.com.",
  deepinfra: "Vision — vault image describes and inbound-photo replies. deepinfra.com.",
  zai: "Chat replies only — GLM models. Not used for vault or photo describes. z.ai.",
  anthropic: "Help assistant answers (Claude Opus). console.anthropic.com.",
  typesafe: "Jev — the FM auto-reply's off-script check, Full AI's Router, the vault AI's Jev pass. Blank = they run on this server's key, if it has one, and the server pays. console.typesafe.ai.",
  nanogpt: "Full AI Chat's first Writer (Euryale v2.3). nano-gpt.com.",
  openrouter: "Full AI Chat's second Writer (Hermes 4 405B). openrouter.ai.",
};

export function clearConfirm(name: string, username?: string): string {
  const label = LABELS[name] ?? name;
  const whose = username === undefined ? "your" : `@${username}'s`;
  if (name === "typesafe") {
    return `Remove ${whose} ${label}? Jev then runs on this server's key and the server pays; with no server key, the off-script check is skipped and Full AI can't go Live.`;
  }
  return username === undefined
    ? `Remove your ${label}? Your models stop replying until you add one.`
    : `Remove ${whose} ${label}? Their models stop replying until one is added.`;
}

export const KEY_URLS: Record<string, string> = {
  deepseek: "https://platform.deepseek.com/api_keys",
  deepinfra: "https://deepinfra.com/dash/api_keys",
  zai: "https://z.ai/manage-apikey/apikey-list",
  anthropic: "https://console.anthropic.com/settings/keys",
  typesafe: "https://console.typesafe.ai/keys",
  nanogpt: "https://nano-gpt.com/api",
  openrouter: "https://openrouter.ai/settings/keys",
  google: "https://console.cloud.google.com/apis/credentials",
};

const SERVER_KEY_PROVIDER: Record<string, string> = {
  DEEPSEEK_API_KEY: "deepseek",
  ZAI_API_KEY: "zai",
  ANTHROPIC_API_KEY: "anthropic",
  TYPESAFE_API_KEY: "typesafe",
  HELP_ASSISTANT_DEEPSEEK_KEY: "deepseek",
  HELP_ASSISTANT_ANTHROPIC_KEY: "anthropic",
  GOOGLE_DRIVE_API_KEY: "google",
};

export function keyUrl(name: string): string | null {
  return KEY_URLS[SERVER_KEY_PROVIDER[name] ?? name] ?? null;
}
