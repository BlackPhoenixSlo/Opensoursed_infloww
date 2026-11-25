"use strict";


// Chrome freezes minor/build/patch at 0.0.0 in its reduced UA. "" when underivable: callers refuse, a malformed UA ("Chrome/.0.0.0") is a unique fingerprint.
function chromeMajor(versions) {
  const major = String((versions && versions.chrome) || "").split(".")[0];
  return /^\d+$/.test(major) ? major : "";
}

function uaProfile(platform, major) {
  const isMac = platform === "darwin";
  return {
    userAgent: isMac
      ? `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Safari/537.36`
      : `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Safari/537.36`,
    platform: isMac ? '"macOS"' : '"Windows"',
  };
}

// Native header rewrite, not CDP: Cloudflare blocks CDP.
function applyClientHints(ses, profile, major) {
  ses.webRequest.onBeforeSendHeaders((details, cb) => {
    const h = details.requestHeaders;
    h["User-Agent"] = profile.userAgent;
    h["sec-ch-ua"] = `"Google Chrome";v="${major}", "Chromium";v="${major}", "Not_A Brand";v="24"`;
    h["sec-ch-ua-mobile"] = "?0";
    h["sec-ch-ua-platform"] = profile.platform;
    cb({ requestHeaders: h });
  });
}

module.exports = { chromeMajor, uaProfile, applyClientHints };
