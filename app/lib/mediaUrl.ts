import { type VaultMedia } from "@/lib/relayTypes";
import { resolveShareToken } from "@/lib/shareToken";

// OF signs CDN urls for the account's egress IP (AWS:SourceIp /32), so the browser 403s; /img fetches via the account's client.
export function proxyImage(
  url: string | null | undefined,
  accountId: string | null | undefined,
  mediaId?: number | null,
): string {
  if (!url) return "";
  if (url.startsWith("blob:") || url.startsWith("data:")) return url;
  if (!accountId) return url;
  const tok = resolveShareToken();
  const params = new URLSearchParams();
  params.set("u", url);
  params.set("account_id", accountId);
  if (mediaId != null) params.set("media_id", String(mediaId));
  if (tok) params.set("t", tok);
  return `/img?${params.toString()}`;
}

export function proxyScrubFrame(
  url: string | null | undefined,
  accountId: string | null | undefined,
  frameIdx: number,
  duration?: number | null,
  sessionId?: string | null,
  mediaId?: number | null,
): string {
  if (!url || !accountId) return "";
  if (url.startsWith("blob:") || url.startsWith("data:")) return "";
  const tok = resolveShareToken();
  const params = new URLSearchParams();
  params.set("u", url);
  params.set("account_id", accountId);
  params.set("i", String(frameIdx));
  if (typeof duration === "number" && duration > 0) {
    params.set("dur", String(duration));
  }
  if (sessionId) params.set("sid", sessionId);
  if (mediaId != null) params.set("media_id", String(mediaId));
  if (tok) params.set("t", tok);
  return `/img/scrub?${params.toString()}`;
}


// _thumb presence = media has a still; chain stops at preview, never files.full (it is the audio file for audio items).
export function vaultTileThumb(
  m: VaultMedia,
  accountId: string | null | undefined,
): string {
  return (
    m._thumb ||
    proxyImage(
      m.files?.thumb?.url || m.files?.squarePreview?.url || m.files?.preview?.url,
      accountId,
    )
  );
}

export function mirrorThumbSrc(accountId: string, mediaId: number | string): string {
  return `/admin/vault-ai/thumb?account_id=${encodeURIComponent(accountId)}&media_id=${encodeURIComponent(String(mediaId))}`;
}

export function mirrorFullSrc(accountId: string, mediaId: number | string): string {
  return `/admin/vault-ai/image?account_id=${encodeURIComponent(accountId)}&media_id=${encodeURIComponent(String(mediaId))}`;
}

export function mirrorPosterSrc(accountId: string, mediaId: number | string, i: number): string {
  return `/admin/vault-ai/poster?account_id=${encodeURIComponent(accountId)}&media_id=${encodeURIComponent(String(mediaId))}&i=${i}`;
}
