"use strict";


function originOf(raw) {
  if (typeof raw !== "string" || !raw) return null;
  try {
    const o = new URL(raw).origin;
    return o && o !== "null" ? o : null;
  } catch {
    return null;
  }
}

function isAppOrigin(raw, appOrigin) {
  return !!appOrigin && originOf(raw) === appOrigin;
}

// installs that kept the old http://inflowwww.com default load the landing site's 404, so the landing site (any scheme) always means the hosted app; http on app 308s, which the shell blocks as off-origin
const LANDING_HOSTS = new Set(["inflowwww.com", "www.inflowwww.com", "app.inflowwww.com"]);
const HOSTED_APP = "https://app.inflowwww.com";

function serverOrigin(origin) {
  try {
    return LANDING_HOSTS.has(new URL(origin).hostname) ? HOSTED_APP : origin;
  } catch {
    return origin;
  }
}

module.exports = { originOf, isAppOrigin, serverOrigin };
