import { chatSwitch, type FullAiConfig } from "@/components/automations/fullAiConfig";


export const PHOTO_PROVIDER = "deepinfra";

export function readsPhotos(sides: (FullAiConfig | null)[]): boolean {
  return sides.some((s) => s !== null && chatSwitch(s, "describe_fan_photos").checked);
}

export function keyRows(
  sides: (FullAiConfig | null)[], providerOf: Record<string, string> | undefined,
  labels: Record<string, string> | undefined,
): { id: string; label: string }[] | null {
  if (!providerOf) return null;
  const writers = sides.flatMap((s) => s?.writers ?? []).map((w) => providerOf[w]).filter(Boolean);
  const ids = [...new Set([...writers, ...(readsPhotos(sides) ? [PHOTO_PROVIDER] : [])])];
  return ids.map((id) => ({ id, label: labels?.[id] ?? id }));
}

export function photoKeyMissing(
  sides: (FullAiConfig | null)[], providers: Record<string, { set: boolean }> | undefined,
): boolean {
  return !!providers && readsPhotos(sides) && !providers[PHOTO_PROVIDER]?.set;
}
