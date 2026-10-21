/** The public site (the "Back to the site" link, the legal links, and the one
 *  origin /site-auth accepts). `NEXT_PUBLIC_SITE_URL` overrides it; Next inlines
 *  that at `next build`, so a container gets it as a build arg (docker-compose.yml
 *  feeds it from SITE_URL in .env). Mirrors `url` in web/src/_data/site.json. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://inflowwww.com").replace(/\/+$/, "");
