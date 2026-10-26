/** The product's name and logo, the one place a deployment renames them.
 *  `NEXT_PUBLIC_BRAND_NAME` / `NEXT_PUBLIC_BRAND_LOGO` override the defaults; Next
 *  inlines them at `next build`, so a container gets them as build args
 *  (docker-compose.yml feeds them from BRAND_NAME / BRAND_LOGO in .env, as it does
 *  SITE_URL). Unset = Inflowwww and the drawn OIF square (SiteLook's IfMark,
 *  public/icon.svg). The relay's twin is service/brand.py. */
export const BRAND_NAME = process.env.NEXT_PUBLIC_BRAND_NAME || "Inflowwww";

/** A round logo image instead of the OIF square: a path prefix under public/ whose
 *  `-512.png` is the mark, `-32.png` the favicon and `-180.png` the Apple touch icon.
 *  Empty = the OIF square. */
export const BRAND_LOGO = process.env.NEXT_PUBLIC_BRAND_LOGO || "";

/** The favicon links (app/layout.tsx metadata.icons). */
export const BRAND_ICONS = BRAND_LOGO
  ? { icon: { url: `${BRAND_LOGO}-32.png`, type: "image/png", sizes: "32x32" }, apple: `${BRAND_LOGO}-180.png` }
  : { icon: { url: "/icon.svg", type: "image/svg+xml", sizes: "any" } };
