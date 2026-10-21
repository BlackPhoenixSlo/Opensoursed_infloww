/** Revoke blob: previews (an upload's chip, an attachment, an unsent
 *  message's files); other URLs are left alone. A no-op without the API
 *  (jsdom). */
export function revokePreviews(urls: Array<string | null | undefined>) {
  if (typeof URL.revokeObjectURL !== "function") return;
  for (const u of urls) if (u?.startsWith("blob:")) URL.revokeObjectURL(u);
}
