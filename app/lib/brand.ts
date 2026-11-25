export const BRAND_NAME = process.env.NEXT_PUBLIC_BRAND_NAME || "Inflowwww";

export const DESKTOP_URL = "/download";
export const DESKTOP_PLATFORMS = "Mac, Windows and Linux";
export const DESKTOP_TITLE = `Get the ${BRAND_NAME} desktop app for ${DESKTOP_PLATFORMS}`;

export const BRAND_LOGO = process.env.NEXT_PUBLIC_BRAND_LOGO || "";

export const BRAND_ICONS = BRAND_LOGO
  ? { icon: { url: `${BRAND_LOGO}-32.png`, type: "image/png", sizes: "32x32" }, apple: `${BRAND_LOGO}-180.png` }
  : { icon: { url: "/icon.svg", type: "image/svg+xml", sizes: "any" } };
