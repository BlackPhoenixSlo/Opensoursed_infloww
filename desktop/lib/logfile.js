"use strict";

// Local main-process log: console.* is mirrored to <userData>/logs/main.log so a
// support request can ask for a file instead of a terminal. Rotation keeps
// `files` files of at most `maxBytes` each (main.log, main.1.log, ...). Share
// tokens never reach disk: `t=` query values and the live token are redacted.
// Uploading the logs on request is not built (it needs a relay endpoint).

const fs = require("fs");
const path = require("path");
const util = require("util");

const T_PARAM = /([?&]t=)[^&#\s"'<>]+/g;

function redact(text, secrets = []) {
  let out = String(text).replace(T_PARAM, "$1[redacted]");
  for (const s of secrets) {
    if (typeof s === "string" && s.length >= 4) out = out.split(s).join("[redacted]");
  }
  return out;
}

function createLogFile({ dir, name = "main", maxBytes = 1024 * 1024, files = 2, getSecrets = () => [] }) {
  const fileAt = (i) => path.join(dir, i === 0 ? `${name}.log` : `${name}.${i}.log`);
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch {
    /* write() will fail quietly */
  }

  function rotate() {
    for (let i = files - 1; i > 0; i--) {
      try {
        fs.renameSync(fileAt(i - 1), fileAt(i));
      } catch {
        /* missing file */
      }
    }
  }

  function write(line) {
    let secrets = [];
    try {
      secrets = getSecrets() || [];
    } catch {
      /* no secrets known yet */
    }
    const data = redact(line, secrets).replace(/\n?$/, "\n");
    try {
      let size = 0;
      try {
        size = fs.statSync(fileAt(0)).size;
      } catch {
        /* no file yet */
      }
      if (size > 0 && size + Buffer.byteLength(data) > maxBytes) rotate();
      fs.appendFileSync(fileAt(0), data, { mode: 0o600 });
    } catch {
      /* logging must never break the app */
    }
  }

  return { dir, file: fileAt(0), write };
}

// Wrap console.<level> so each call still prints, then goes to the log file.
function mirrorConsole(consoleObj, log, now = () => new Date().toISOString()) {
  let busy = false; // getSecrets may itself log; don't recurse.
  for (const level of ["log", "info", "warn", "error", "debug"]) {
    const orig = consoleObj[level];
    if (typeof orig !== "function") continue;
    consoleObj[level] = function (...args) {
      orig.apply(consoleObj, args);
      if (busy) return;
      busy = true;
      try {
        log.write(`${now()} [${level}] ${util.format(...args)}`);
      } finally {
        busy = false;
      }
    };
  }
}

module.exports = { redact, createLogFile, mirrorConsole };
