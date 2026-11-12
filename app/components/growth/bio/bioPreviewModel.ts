/**
 * What the bio editor's live preview draws (BioPreview): the profile as edited and the links as saved, with the link
 * open in the dialog drawn as edited (in its place, or last when new). The public page's rules (`script.js` renderLinks,
 * `decide.public_profile`): a link's mode is its own if recognised, else the profile's, else Escape; the subtitle is
 * "Exclusive Content" behind the 18+ gate, else "Social Media"; the icon shows only on a background image.
 * `trackingUrl` is a tracking code's address on the page.
 */
import { isBioMode, stockIconUrl, type BioLink, type BioMode } from "@/hooks/useBioPages";
import type { OfTrackingLink } from "@/hooks/useGrowth";
import type { BioLinkForm } from "@/components/growth/bio/bioLinkForm";

/** One link as the preview reads it, saved or being edited (`id` null: a new one). */
export interface LinkView {
  id: string | null;
  title: string;
  isAdult: boolean;
  mode: string;
  iconUrl: string;
  backgroundUrl: string;
}

export interface PreviewLink {
  key: string;
  title: string;
  isAdult: boolean;
  mode: BioMode;
  subtitle: string;
  /** Empty without a background image: the public page draws no icon on a plain card. */
  iconUrl: string;
  backgroundUrl: string;
}

export interface PreviewModel {
  displayName: string;
  bio: string;
  verified: boolean;
  avatarUrl: string;
  mode: BioMode;
  links: PreviewLink[];
}

export interface PreviewProfile { displayName: string; bio: string; verified: boolean; mode: string; avatarUrl: string }

const known = isBioMode;

export const linkView = (l: BioLink): LinkView => ({
  id: l.id, title: l.title, isAdult: l.is_adult, mode: l.mode, iconUrl: l.icon_url, backgroundUrl: l.background_url,
});

/** The dialog's link as edited, or undefined while it is closed. `bgObjectUrl`: the picked file's object URL. */
export function draftLinkView(form: BioLinkForm, bgObjectUrl: string | null): LinkView | undefined {
  if (!form.open) return undefined;
  const { draft, base } = form;
  const iconUrl = draft.icon === "none" ? "" : draft.icon === "current" ? base?.icon_url ?? "" : stockIconUrl(draft.icon);
  const backgroundUrl = bgObjectUrl ?? (form.bgRemove ? "" : base?.background_url ?? "");
  return {
    id: base?.id ?? null,
    title: draft.title, isAdult: draft.isAdult, mode: draft.mode, iconUrl, backgroundUrl,
  };
}

export function previewModel(profile: PreviewProfile, links: readonly BioLink[], linkDraft?: LinkView): PreviewModel {
  const mode: BioMode = known(profile.mode) ? profile.mode : "escape_ig";
  const views = links.map(linkView);
  if (linkDraft) {
    const at = linkDraft.id === null ? -1 : views.findIndex((v) => v.id === linkDraft.id);
    if (at >= 0) views[at] = linkDraft;
    else views.push(linkDraft);
  }
  return {
    displayName: profile.displayName, bio: profile.bio, verified: profile.verified, avatarUrl: profile.avatarUrl, mode,
    links: views.map((v) => ({
      key: v.id ?? "new",
      title: v.title,
      isAdult: v.isAdult,
      mode: known(v.mode) ? v.mode : mode,
      subtitle: v.isAdult ? "Exclusive Content" : "Social Media",
      iconUrl: v.backgroundUrl ? v.iconUrl : "",
      backgroundUrl: v.backgroundUrl,
    })),
  };
}

/** A background image's natural size, stored under its URL by BioPreview. */
export interface ImageSize { width: number; height: number }

/**
 * A background card's CSS aspect-ratio, as the public page sets it (`style.css` .link-card.has-bg-image, `script.js`
 * img.onload): 2.5:1 until the image has loaded, then the image's natural ratio. The URL-keyed size map handles
 * changed images; a degenerate size keeps 2.5:1.
 */
export function bgAspectRatio(size: ImageSize | null): string {
  if (!size || !(size.width > 0) || !(size.height > 0)) return "2.5 / 1";
  return `${size.width / size.height} / 1`;
}

/** A tracking code's address on the page: `…/alice` + `123` → `…/alice/123`; a custom domain's `https://d/` → `https://d/123`. */
export const trackingUrl = (publicUrl: string, code: string) =>
  publicUrl.endsWith("/") ? `${publicUrl}${code}` : `${publicUrl}/${code}`;

export const trackingRows = (links: readonly Pick<OfTrackingLink, "id" | "code" | "name" | "is_deleted">[], address: string) => links
  .filter((l) => l.code != null && !l.is_deleted)
  .map((l) => ({ key: `${l.id}-${l.code}`, name: l.name, code: String(l.code), url: trackingUrl(address, String(l.code)) }));
