"use strict";


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
      return {};
    }
  }

  _write() {
    const tmp = `${this.file}.tmp`;
    try {
      fs.writeFileSync(tmp, JSON.stringify(this.data, null, 2), {
        encoding: "utf8",
        mode: 0o600, // owner read/write only: the share token is in here
      });
      fs.renameSync(tmp, this.file);
    } catch (err) {
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
