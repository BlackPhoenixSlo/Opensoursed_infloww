/**
 * providerFields — how an LLM provider reads in the UI, and the one paste
 * mistake worth warning about.
 *
 * Shared because there are two places to type a provider key and they must say
 * the same things: the owner's own card (Settings → AI keys) and the founder's
 * form for another agency (Setup → Other agencies' AI keys, and Admin → Manage).
 * They did not: the founder's form — the one actually used to key an agency —
 * showed raw ids like "deepinfra" and carried no wrong-field warning at all,
 * which is precisely where a DeepSeek key got pasted into the DeepInfra box.
 */

/** Provider id → how it reads in the UI. An id with no entry renders as itself,
 *  so a provider added to the server registry shows up with no frontend deploy. */
export const LABELS: Record<string, string> = {
  deepseek: "DeepSeek API key",
  deepinfra: "DeepInfra API key",
  zai: "Z.ai (GLM) API key",
  anthropic: "Anthropic (Claude) API key",
  typesafe: "TypeSafe (Jev) API key",
  nanogpt: "NanoGPT API key",
  openrouter: "OpenRouter API key",
};

/** A DeepSeek key is `sk-` + 32 hex and nothing else on this list looks like
 *  that, so a value in that shape sitting in another provider's field is a
 *  paste into the wrong box — the single most likely way to configure this
 *  card wrong, and one that fails SILENTLY: the key stores fine, and the first
 *  sign of trouble is that provider's calls 401ing later.
 *
 *  A warning, never a block. Key formats are the vendor's to change, and being
 *  wrong about a shape must not stop someone saving a key that works. */
const DEEPSEEK_SHAPE = /^sk-[0-9a-f]{32}$/i;
/** Every Anthropic key starts `sk-ant-` (api03 / admin / usr variants). */
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
  // tenant_keys.typesafe_key_for: an agency with no key of its own runs Jev on the server's (it pays).
  typesafe: "Jev — the FM auto-reply's off-script check, Full AI's Router, the vault AI's Jev pass. Blank = they run on this server's key, if it has one, and the server pays. console.typesafe.ai.",
  nanogpt: "Full AI Chat's first Writer (Euryale v2.3). nano-gpt.com.",
  openrouter: "Full AI Chat's second Writer (Hermes 4 405B). openrouter.ai.",
};

/** The clear link's confirm: the owner's own card (no `username`) or the founder's form for @`username`. A
 *  cleared TypeSafe key does not stop anything: Jev falls back to the server's key (`tenant_keys.typesafe_key_for`). */
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

/** Provider id → the vendor page where you create / copy an API key (not the
 *  sign-up page), linked under every key field so nobody has to search for it.
 *  Logged-out visitors land on the vendor's login, which bounces back here. */
export const KEY_URLS: Record<string, string> = {
  deepseek: "https://platform.deepseek.com/api_keys",
  deepinfra: "https://deepinfra.com/dash/api_keys",
  zai: "https://z.ai/manage-apikey/apikey-list",
  anthropic: "https://console.anthropic.com/settings/keys",
  typesafe: "https://console.typesafe.ai/keys",   // docs.typesafe.ai/quickstart "Get an API key"
  nanogpt: "https://nano-gpt.com/api",
  openrouter: "https://openrouter.ai/settings/keys",
  google: "https://console.cloud.google.com/apis/credentials",
};

/** Server secrets-store key (service/secrets_store.py KNOWN) → provider id in
 *  KEY_URLS. Keys with no vendor (passwords, share token) have no entry. */
const SERVER_KEY_PROVIDER: Record<string, string> = {
  DEEPSEEK_API_KEY: "deepseek",
  ZAI_API_KEY: "zai",
  ANTHROPIC_API_KEY: "anthropic",
  TYPESAFE_API_KEY: "typesafe",
  HELP_ASSISTANT_DEEPSEEK_KEY: "deepseek",
  HELP_ASSISTANT_ANTHROPIC_KEY: "anthropic",
  GOOGLE_DRIVE_API_KEY: "google",
};

/** The key page for a provider id or a server key name, or null. */
export function keyUrl(name: string): string | null {
  return KEY_URLS[SERVER_KEY_PROVIDER[name] ?? name] ?? null;
}
