"use strict";


const { execFile } = require("child_process");
const path = require("path");

const CODESIGN_TIMEOUT_MS = 4000;

function bundlePath(execPath) {
  return path.resolve(execPath, "..", "..", "..");
}

function classify(output) {
  const text = String(output || "");
  if (/code object is not signed at all/i.test(text)) return { kind: "unsigned", teamId: null };

  const team = text.match(/^TeamIdentifier=(.+)$/m);
  const teamId = team && team[1].trim() !== "not set" ? team[1].trim() : null;

  // Check ad-hoc BEFORE trusting a Team ID: the flags line is authoritative and an ad-hoc signature never has a meaningful team.
  if (/\badhoc\b/i.test(text) || /^Signature=adhoc$/m.test(text)) {
    return { kind: "adhoc", teamId: null };
  }
  if (teamId) return { kind: "developer-id", teamId };
  if (/^Signature=/m.test(text) || /^Authority=/m.test(text)) {
    return { kind: "developer-id", teamId: null };
  }
  return { kind: "unknown", teamId: null };
}

function describeSigning(deps = {}) {
  const {
    platform = process.platform,
    isPackaged = true,
    electronVersion = process.versions.electron,
    execPath = process.execPath,
    run = execFile,
  } = deps;

  const electronMajor = parseInt(String(electronVersion), 10) || 0;
  const base = {
    platform,
    isPackaged,
    electronMajor,
    // hypothesis, unconfirmed: Electron 42 macOS notifications need a signed app; packaged builds fail silently
    notificationsRequireSigning: platform === "darwin" && electronMajor >= 42,
    kind: "not-applicable",
    teamId: null,
  };

  if (platform !== "darwin" || !isPackaged) return Promise.resolve(base);

  return new Promise((resolve) => {
    let settled = false;
    const done = (result) => {
      if (settled) return;
      settled = true;
      resolve({ ...base, ...result });
    };

    try {
      run(
        "codesign",
        ["-dv", "--verbose=2", bundlePath(execPath)],
        { timeout: CODESIGN_TIMEOUT_MS },
        (err, stdout, stderr) => {
          // codesign reports on STDERR and exits non-zero for an unsigned bundle: a non-zero exit is data, not a failure.
          const text = `${stderr || ""}\n${stdout || ""}`;
          if (!text.trim()) return done({ kind: err ? "unknown" : "unknown" });
          done(classify(text));
        }
      );
    } catch {
      done({ kind: "unknown" });
    }
  });
}

function summarize(d) {
  if (d.platform !== "darwin") return `signing: n/a (${d.platform})`;
  if (!d.isPackaged) return "signing: n/a (dev build runs inside Electron's own signed app)";
  const team = d.teamId ? ` team=${d.teamId}` : "";
  return (
    `signing: ${d.kind}${team} · electron=${d.electronMajor} · ` +
    `notifications require signing: ${d.notificationsRequireSigning ? "yes" : "no"}`
  );
}

module.exports = { describeSigning, classify, summarize, bundlePath };
