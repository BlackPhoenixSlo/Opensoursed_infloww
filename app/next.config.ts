import type { NextConfig } from "next";

/**
 * Dev rewrites: the browser only ever talks to localhost:3001 (the
 * Next.js dev server). Anything that's a relay endpoint — signed OF
 * paths, admin CRUD, SSE — gets transparently proxied to the Python
 * relay on localhost:8787. This keeps the share-token cookie + the
 * SameSite story trivial, and the relay never sees CORS preflight.
 *
 * Production (docker-compose.yml): Traefik sends /api/of/, /admin/, /img,
 * /events, /auth/ and /chatter/ straight to the relay, so those rewrites
 * only serve dev; every other relay path below still goes through them.
 * A rewrite added here that changes the path needs the same change there.
 */

const RELAY_URL = process.env.RELAY_URL || "http://127.0.0.1:8787";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // `scripts/ui-shots.sh` runs a second dev server from this directory while
  // yours may hold `.next` (Next refuses two servers per build directory), so
  // it sets NEXT_DIST_DIR=.next/ui-shots. Unset, nothing changes.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Next 16 blocks cross-origin dev requests by default. The dev server binds
  // to `localhost:3001` but you may visit via `127.0.0.1:3001` (or LAN IP) —
  // without this, the HMR + chunk loaders 403 and hydration silently stalls
  // on the SSR placeholder.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // App Router client-side cache. Next 15+ defaulted `dynamic` to 0s, so
  // every back-navigation re-fetches the RSC payload — surfaces as the
  // dev "Rendering…" indicator stalling on Inbox → Home even after Home
  // has already been visited once. Bumping to 60s keeps just-visited
  // routes instant; the SSE + per-query staleTime layer still controls
  // data freshness, this only governs the React tree cache.
  // Next caps a body proxied by the rewrites below at 10 MB by default: a 73 MB
  // vault import was truncated mid-multipart, the relay dropped the
  // half-written body, and the browser saw a socket hang up while the import
  // card sat on "Starting…" forever. (The runtime warning names
  // `middlewareClientMaxBodySize`; that key is deprecated in Next 16 —
  // `proxyClientMaxBodySize` is the live one.)
  //
  // In production the upload routes (/api/of/…, /admin/…) go Traefik -> relay
  // and never pass through here (docker-compose.yml), so this cap governs dev
  // only. NOT raised to match VAULT_UPLOAD_MAX_MB (4000): the dev server holds
  // the body in memory, and 256 MB covers ordinary imports; for a multi-GB file
  // use a Drive link, which the relay fetches server-side.
  experimental: {
    proxyClientMaxBodySize: "256mb",
    staleTimes: {
      dynamic: 60,
      static: 300,
    },
  },
  async redirects() {
    // Pre-Infloww URLs → the Infloww route map (docs/infloww-screens.md §2).
    // Bookmarks, the help assistant's links, push notifications and relay
    // `chat_href`s still use the old addresses. Non-permanent on purpose: the
    // map may still move. The query string rides along, so /messages?tab=tips
    // lands on the same tab. Old `?tab=` values become their own pages via
    // `has` rules, which must come before the bare-path rule for that path.
    const tab = (source: string, value: string, destination: string) => ({
      source,
      has: [{ type: "query" as const, key: "tab", value }],
      destination,
      permanent: false,
    });
    const to = (source: string, destination: string) => ({ source, destination, permanent: false });
    return [
      // The owed-customs queue, once its own nav entry, is a tab of the
      // Message dashboard (ex-"Stuff"). A config redirect, not a page: a page
      // here would prerender a 200 and only redirect after hydration.
      to("/customs", "/analytics/message-dashboard?tab=customs"),
      // The static Infloww clone the relay once served at /infloww is gone; its old links land on Home.
      to("/infloww", "/"),
      to("/infloww/:path*", "/"),
      to("/inbox", "/messages-pro"),
      to("/chat/:path*", "/messages-pro/:path*"),
      to("/messages", "/analytics/message-dashboard"),
      to("/stats", "/analytics/employee-reports"),
      to("/vault", "/growth/vault-pro"),
      to("/setup", "/creators"),
      // The Organization Chart tab is Manage employees' group tree now (page-parity ticket 17).
      to("/employees/org-chart", "/employees"),
      tab("/growth", "smart", "/growth/smart-lists"),
      tab("/growth", "trial", "/growth/free-trial-links"),
      tab("/growth", "tracking", "/growth/tracking-links"),
      tab("/growth", "promotion", "/growth/profile-promotion"),
      tab("/growth", "auto_follow", "/growth/auto-follow"),
      to("/growth", "/growth/smart-lists"),
      tab("/settings", "employees", "/employees"),
      tab("/settings", "chatters", "/employees"),
      tab("/settings", "templates", "/growth/scripts"),
      tab("/settings", "scheduled", "/growth/smart-messages"),
      tab("/settings", "mass", "/growth/smart-messages"),
      tab("/settings", "stories", "/growth/auto-story"),
      tab("/settings", "audit", "/settings/audit"),
      to("/settings", "/settings/account"),
      // OF Manager's Reserved usernames is turned off (scripts/of-mirror.mjs SETTINGS_OFF): its URL opens Security.
      to("/of-manager/settings/security/reserved_usernames", "/of-manager/settings/security"),
      // Infloww's Statistics menu lands on Statements › Earnings; OF's own links name Overview (scripts/of-mirror.mjs LINK_INDEX).
      to("/of-manager/statistics", "/of-manager/statistics/statements/earnings"),
      // Statements' Chargebacks is Statistics' (OF redirects /my/stats/disputes there; scripts/of-mirror.mjs REDIRECTS).
      to("/of-manager/statements/stats/disputes", "/of-manager/statistics/statements/disputes"),
      // The pre-Infloww /automations page is gone: Auto Posts lives in My Automations…
      {
        source: "/automations",
        has: [{ type: "query" as const, key: "ready", value: "auto_posts" }],
        destination: "/growth/auto-post",
        permanent: false,
      },
      // …and Premade Mass, as My Automations > Auto Mass.
      {
        source: "/automations",
        has: [{ type: "query" as const, key: "ready", value: "mass_premade" }],
        destination: "/growth/auto-mass",
        permanent: false,
      },
      // …and any other old /automations link lands on its first page.
      to("/automations", "/growth/auto-post"),
    ];
  },
  async rewrites() {
    return [
      // Health + admin CRUD (employees, audit, accounts, proxies, sessions, rev).
      // This `/admin/:path*` catch-all already proxies every admin endpoint to
      // the relay, including the message GET seed (18_chat_render_stability
      // §1.1). No dedicated entry is needed — but note the relay-rewrite footgun: a NEW top-level
      // path OUTSIDE this prefix (or a Next page that shadows it, e.g.
      // app/admin/manage) would 404 before reaching the relay.
      { source: "/health",       destination: `${RELAY_URL}/health` },
      { source: "/admin/:path*", destination: `${RELAY_URL}/admin/:path*` },
      // Friend auth (register/login/logout/me) — must be reachable before
      // the share-token gate (the relay exempts /auth/* on its end too).
      { source: "/auth/:path*",  destination: `${RELAY_URL}/auth/:path*` },
      // Chatter principal (login/logout/register/me/me-owners/me-accounts).
      // Mirror of /auth/* but for the second principal — see
      // service/chatters.py. The relay's share-token gate exempts
      // /chatter/* too so a brand-new chatter following an invite link
      // can reach /chatter/register without a cookie. Owner-side
      // chatter management lives under /admin/chatters/* which is
      // already covered by the broader /admin/:path* rewrite above.
      { source: "/chatter/:path*", destination: `${RELAY_URL}/chatter/:path*` },
      // The signed OF mirror — anything the browser asks at /api/of/v2/*
      // we proxy untouched.
      { source: "/api/of/:path*", destination: `${RELAY_URL}/api/of/:path*` },
      // CDN image proxy — relay tunnels the fetch through the account's
      // own egress IP, since OF CDN URLs are signed to a specific source IP.
      // /img is the base proxy; /img/scrub and /img/by-hash are sub-routes
      // for the storyboard cache and the stable-hash alias.
      { source: "/img",            destination: `${RELAY_URL}/img` },
      { source: "/img/:path*",     destination: `${RELAY_URL}/img/:path*` },
      // SSE channel.
      { source: "/events",       destination: `${RELAY_URL}/events` },
      // The Concurrency panel, served by the relay and UNAUTHENTICATED there
      // (`service/lane_config_api.py`, on `server.py`'s no-auth allowlist).
      // Until 2026-09-20 this rewrite was deliberately absent so the panel
      // was reachable only on the relay's loopback port; the operator then
      // decided it must open for anyone who pastes https://<host>/lanes-panel
      // with no login, no token and no secret key, and reaffirmed that after
      // being told one of its routes restarts the relay. What still bounds
      // it: the restart budget (two per hour, on disk), the JSON-body CSRF
      // guard, and the fact that every ceiling applies at restart only.
      // Do not add a rewrite for any other relay page without checking what
      // gates it on the relay side.
      { source: "/lanes-panel",        destination: `${RELAY_URL}/lanes-panel` },
      { source: "/lanes-panel/:path*", destination: `${RELAY_URL}/lanes-panel/:path*` },
      // Public tracking-link redirect (Growth → Tracking Links). A fan hits
      // /t/<slug>; the relay records the click and 302s to the target. Must be
      // a top-level rewrite — it's outside the /admin/* prefix.
      { source: "/t/:slug", destination: `${RELAY_URL}/t/:slug` },
      // A share link's public report (Growth → Share links): the page
      // /share/<key> is Next's; only its /data read goes to the relay.
      { source: "/share/:key/data", destination: `${RELAY_URL}/share/:key/data` },
      // Desktop-app download page. Unlike everything above this is served by
      // Next itself out of `public/download.html` — it is deliberately NOT a
      // relay path, so it stays reachable with no share token and no login,
      // which is the whole point: it is linked from the login screens.
      { source: "/download", destination: "/download.html" },
    ];
  },
  // Skip image optimization for now — OF media URLs are CDN-hosted with
  // their own caching; Next's loader adds latency for no gain.
  images: { unoptimized: true },
};

export default nextConfig;
