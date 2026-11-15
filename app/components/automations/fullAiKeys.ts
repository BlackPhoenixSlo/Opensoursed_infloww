import { chatSwitch, type FullAiConfig } from "@/components/automations/fullAiConfig";

/** Full AI Chat's LLM keys row: the providers the Writers run on (draft and saved checkpoint), plus the vision provider
 *  while "Read his photos" is on, named by the config GET's `provider_labels` (as the keys form names them; an unknown provider id
 *  renders as itself). */

/** The provider "Read his photos" bills (`inbound_describe.PROVIDER`). */
export const PHOTO_PROVIDER = "deepinfra";

/** "Read his photos" on in a loaded side (draft or checkpoint); a side without the key reads the default, on. */
export function readsPhotos(sides: (FullAiConfig | null)[]): boolean {
  return sides.some((s) => s !== null && chatSwitch(s, "describe_fan_photos").checked);
}

/** Each provider once, in Writer order (draft first, then the checkpoint's), then the photo provider while
 *  `readsPhotos`; a model with no provider is skipped. null while the config GET's `writer_providers` has not answered. */
export function keyRows(
  sides: (FullAiConfig | null)[], providerOf: Record<string, string> | undefined,
  labels: Record<string, string> | undefined,
): { id: string; label: string }[] | null {
  if (!providerOf) return null;
  const writers = sides.flatMap((s) => s?.writers ?? []).map((w) => providerOf[w]).filter(Boolean);
  const ids = [...new Set([...writers, ...(readsPhotos(sides) ? [PHOTO_PROVIDER] : [])])];
  return ids.map((id) => ({ id, label: labels?.[id] ?? id }));
}

/** Photos are read but the keys read says no DeepInfra key: the page warns (not a Live blocker, the Turn answers
 *  without the photo). false while the keys read has not answered. */
export function photoKeyMissing(
  sides: (FullAiConfig | null)[], providers: Record<string, { set: boolean }> | undefined,
): boolean {
  return !!providers && readsPhotos(sides) && !providers[PHOTO_PROVIDER]?.set;
}
