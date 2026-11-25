import type { MetadataRoute } from "next";

import { BRAND_LOGO, BRAND_NAME } from "@/lib/brand";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: BRAND_NAME,
    short_name: BRAND_NAME,
    // standalone is what iOS needs for Web Push
    display: "standalone",
    start_url: "/",
    icons: BRAND_LOGO
      ? [
          { src: `${BRAND_LOGO}-180.png`, sizes: "180x180", type: "image/png" },
          { src: `${BRAND_LOGO}-512.png`, sizes: "512x512", type: "image/png" },
        ]
      : [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
  };
}
