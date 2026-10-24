"use strict";

// The one origin comparison the shell uses for trust decisions (IPC senders,
// permissions) and navigation. Origins are compared PARSED, so "https://host/"
// and "https://host" match; anything unparsable, opaque ("null") or empty is
// no origin.
//
// Rule for "no server configured" (appOrigin null): isAppOrigin is false, so
// trust checks DENY. Nothing remote is loaded then (the Settings window shows),
// so there is no legitimate remote caller to allow.

/** Parsed origin of a URL string, or null. */
function originOf(raw) {
  if (typeof raw !== "string" || !raw) return null;
  try {
    const o = new URL(raw).origin;
    return o && o !== "null" ? o : null;
  } catch {
    return null;
  }
}

/** True only when `raw` parses to exactly `appOrigin` (and one is configured). */
function isAppOrigin(raw, appOrigin) {
  return !!appOrigin && originOf(raw) === appOrigin;
}

// inflowwww.com is the marketing site; the hosted app is app.inflowwww.com.
// Builds before 2026-10-21 defaulted the Server URL to http://inflowwww.com, so
// installs that kept it have the landing site saved and load its 404 (/inbox)
// or its home page (/). The landing site (apex or www, either scheme) is never
// a server, so it always means the app.
const LANDING_HOSTS = new Set(["inflowwww.com", "www.inflowwww.com"]);
const HOSTED_APP = "https://app.inflowwww.com";

/** The server origin to use for a parsed origin: the landing site → the hosted app. */
function serverOrigin(origin) {
  try {
    return LANDING_HOSTS.has(new URL(origin).hostname) ? HOSTED_APP : origin;
  } catch {
    return origin;
  }
}

module.exports = { originOf, isAppOrigin, serverOrigin };
