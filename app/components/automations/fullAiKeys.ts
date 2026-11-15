/** Full AI Chat's LLM keys row: the providers the Writers run on (draft and saved checkpoint), short names as the
 *  keys form reads them. An unknown provider id renders as itself. */
export const KEY_LABELS: Record<string, string> = {
  nanogpt: "NanoGPT", openrouter: "OpenRouter", zai: "Z.ai", deepseek: "DeepSeek", deepinfra: "DeepInfra",
};

/** Each provider once, in Writer order (draft first, then the checkpoint's); a model with no provider is skipped.
 *  null while the config GET's `writer_providers` has not answered. */
export function writerKeyRows(
  writerLists: (string[] | undefined)[], providerOf: Record<string, string> | undefined,
): { id: string; label: string }[] | null {
  if (!providerOf) return null;
  const ids = [...new Set(writerLists.flatMap((ws) => ws ?? []).map((w) => providerOf[w]).filter(Boolean))];
  return ids.map((id) => ({ id, label: KEY_LABELS[id] ?? id }));
}
