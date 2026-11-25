export function revokePreviews(urls: Array<string | null | undefined>) {
  if (typeof URL.revokeObjectURL !== "function") return;
  for (const u of urls) if (u?.startsWith("blob:")) URL.revokeObjectURL(u);
}
