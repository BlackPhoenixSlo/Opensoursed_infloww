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

module.exports = { originOf, isAppOrigin };
