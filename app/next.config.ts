import { existsSync } from "node:fs";
import path from "node:path";

import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants";


const RELAY_URL = process.env.RELAY_URL || "http://127.0.0.1:8787";
const BIO_URL = process.env.BIO_URL || "http://127.0.0.1:8788";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Next 16 blocks cross-origin dev requests; without this HMR/chunk loaders 403 and hydration stalls.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  experimental: {
    // Default 10 MB cap truncated a 73 MB vault import mid-multipart; dev-only (prod upload routes bypass Next). Not raised to VAULT_UPLOAD_MAX_MB: dev server buffers the body.
    proxyClientMaxBodySize: "256mb",
    // Next 15+ defaults dynamic to 0s, so back-navigation refetches the RSC payload.
    staleTimes: {
      dynamic: 60,
      static: 300,
    },
  },
  async redirects() {
    const tab = (source: string, value: string, destination: string) => ({
      source,
      has: [{ type: "query" as const, key: "tab", value }],
      destination,
      permanent: false,
    });
    const to = (source: string, destination: string) => ({ source, destination, permanent: false });
    return [
      // Non-permanent: the route map may still move. Tab rules via `has` must precede the bare-path rule.
      to("/customs", "/analytics/message-dashboard?tab=customs"),
      to("/infloww", "/"),
      to("/infloww/:path*", "/"),
      to("/inbox", "/messages-pro"),
      to("/chat/:path*", "/messages-pro/:path*"),
      to("/messages", "/analytics/message-dashboard"),
      to("/stats", "/analytics/employee-reports"),
      to("/vault", "/growth/vault-pro"),
      to("/setup", "/creators"),
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
      to("/of-manager/settings/security/reserved_usernames", "/of-manager/settings/security"),
      to("/of-manager/statistics", "/of-manager/statistics/statements/earnings"),
      to("/of-manager/statements/stats/disputes", "/of-manager/statistics/statements/disputes"),
      {
        source: "/automations",
        has: [{ type: "query" as const, key: "ready", value: "auto_posts" }],
        destination: "/growth/auto-post",
        permanent: false,
      },
      {
        source: "/automations",
        has: [{ type: "query" as const, key: "ready", value: "mass_premade" }],
        destination: "/growth/auto-mass",
        permanent: false,
      },
      to("/automations", "/growth/auto-post"),
    ];
  },
  // Keep dev rewrites aligned with Traefik, where /admin/manage goes to Next.
  async rewrites() {
    return [
      { source: "/health",       destination: `${RELAY_URL}/health` },
      { source: "/admin/:path*", destination: `${RELAY_URL}/admin/:path*` },
      // Must be reachable before the share-token gate (relay exempts /auth/* and /chatter/* too).
      { source: "/auth/:path*",  destination: `${RELAY_URL}/auth/:path*` },
      { source: "/.well-known/oauth-protected-resource/:path*", destination: `${RELAY_URL}/.well-known/oauth-protected-resource/:path*` },
      { source: "/.well-known/oauth-authorization-server/:path*", destination: `${RELAY_URL}/.well-known/oauth-authorization-server/:path*` },
      { source: "/chatter/:path*", destination: `${RELAY_URL}/chatter/:path*` },
      { source: "/api/of/:path*", destination: `${RELAY_URL}/api/of/:path*` },
      // Relay fetches CDN images via the account's egress IP: OF CDN URLs are signed to a source IP.
      { source: "/img",            destination: `${RELAY_URL}/img` },
      { source: "/img/:path*",     destination: `${RELAY_URL}/img/:path*` },
      { source: "/events",       destination: `${RELAY_URL}/events` },
      { source: "/push/:path*",  destination: `${RELAY_URL}/push/:path*` },
      // Unauthenticated by owner decision; bounded by relay restart budget and CSRF guard. Add no other relay page without checking its gate.
      { source: "/lanes-panel",        destination: `${RELAY_URL}/lanes-panel` },
      { source: "/lanes-panel/:path*", destination: `${RELAY_URL}/lanes-panel/:path*` },
      { source: "/t/:slug", destination: `${RELAY_URL}/t/:slug` },
      { source: "/t/:slug/verify", destination: `${RELAY_URL}/t/:slug/verify` },
      { source: "/share/:key/data", destination: `${RELAY_URL}/share/:key/data` },
      { source: "/p/:path*", destination: `${BIO_URL}/p/:path*` },
      // Served by Next out of public/download.html, deliberately not a relay path: reachable with no share token or login.
      { source: "/download", destination: "/download.html" },
    ];
  },
  // OF media is CDN-hosted with its own caching; Next's loader only adds latency.
  images: { unoptimized: true },
};

export default function config(phase: string): NextConfig {
  // Dev/build only: `next start` (Docker runner has no lib/) loads this file too.
  if (phase === PHASE_DEVELOPMENT_SERVER || phase === PHASE_PRODUCTION_BUILD) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { writePluginBarrel } = require("./lib/pluginBarrel.js") as { writePluginBarrel: (appRoot: string) => string[] };
    writePluginBarrel(__dirname);
    const mirror = existsSync(path.join(__dirname, "public/fansly-mirror/pages"));
    return { ...nextConfig, env: { NEXT_PUBLIC_FANSLY_MIRROR_ABSENT: mirror ? "" : "1" } };
  }
  return nextConfig;
}
