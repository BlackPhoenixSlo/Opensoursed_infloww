"use strict";

// Tiny zero-dependency JSON config store, persisted under Electron's per-user
// `userData` dir. We hand-roll this instead of pulling in `electron-store` to
// (a) keep `desktop/` dependency-light and (b) avoid the CJS/ESM churn that
// electron-store's v9+ ESM-only releases introduced. The whole store is a
// single small JSON object read/written atomically.
//
// What lives here: the server URL, the share token, a per-token "seeded" marker
// (so we only put the token in a navigated URL on first seed — see main.js), the
// "Don't show this again" flag for the launch-time Settings window, and the last
// window bounds. NOTHING here is an OF credential — the OF session lives
// server-side on the relay; the only secret is the relay share token, which is a
// link-gate token, not an account password.

const fs = require("fs");
const path = require("path");

class Store {
  constructor(userDataDir) {
    this.file = path.join(userDataDir, "fastt-desktop-config.json");
    this.data = this._read();
  }

  _read() {
    try {
      const raw = fs.readFileSync(this.file, "utf8");
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      // Missing / unreadable / corrupt → start clean. First run lands here.
      return {};
    }
  }

  _write() {
    // Atomic write: temp file + rename, so a crash mid-write can't corrupt the
    // config and strand the user at a blank first-run screen.
    const tmp = `${this.file}.tmp`;
    try {
      fs.writeFileSync(tmp, JSON.stringify(this.data, null, 2), {
        encoding: "utf8",
        mode: 0o600, // owner read/write only — the token is in here.
      });
      fs.renameSync(tmp, this.file);
    } catch (err) {
      // Non-fatal: config just won't persist this change. Surface for logs.
      console.error("[store] write failed:", err && err.message);
    }
  }

  get(key, fallback) {
    return Object.prototype.hasOwnProperty.call(this.data, key)
      ? this.data[key]
      : fallback;
  }

  set(key, value) {
    this.data[key] = value;
    this._write();
  }

  setMany(obj) {
    Object.assign(this.data, obj);
    this._write();
  }

  delete(key) {
    delete this.data[key];
    this._write();
  }

  all() {
    return { ...this.data };
  }
}

module.exports = { Store };
