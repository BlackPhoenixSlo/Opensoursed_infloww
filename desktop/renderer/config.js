"use strict";

// Settings page logic. Talks to the main process only through the bridged
// `window.fasttNative` surface (see config-preload.js). No network, no Node.
// Also the load-failure screen: main.js opens it with ?desc=&url= when the app
// failed to load; we render that read-only (textContent, never innerHTML).

const DEFAULT_SERVER_URL = "https://app.inflowwww.com";

const urlEl = document.getElementById("url");
const tokenEl = document.getElementById("token");
const tokenHint = document.getElementById("tokenHint");
const skipEl = document.getElementById("skip");
const errEl = document.getElementById("err");
const saveBtn = document.getElementById("save");
const quitBtn = document.getElementById("quit");
const hwAccelEl = document.getElementById("hwAccel");
const secureDnsEl = document.getElementById("secureDns");
const restartBtn = document.getElementById("restart");

const advanced = () => ({ hwAccel: hwAccelEl.checked, secureDns: secureDnsEl.checked });

const params = new URLSearchParams(window.location.search);
const problem = [params.get("desc"), params.get("url")].filter(Boolean).join("  ·  ");
if (problem) {
  document.getElementById("problemDetail").textContent = problem;
  document.getElementById("problem").hidden = false;
  document.getElementById("intro").hidden = true; // keep the form in view
}

async function hydrate() {
  urlEl.value = DEFAULT_SERVER_URL;
  try {
    const cfg = await window.fasttNative.getConfig();
    if (cfg) {
      urlEl.value = cfg.serverUrl || DEFAULT_SERVER_URL;
      hwAccelEl.checked = cfg.hwAccel !== false;
      secureDnsEl.checked = cfg.secureDns === true;
      skipEl.checked = !!cfg.skipStartupSettings;
      document.getElementById("reopenHint").hidden = !cfg.isMac;
      if (cfg.hasToken) {
        tokenEl.placeholder = "•••••••• (unchanged)";
        tokenHint.textContent = "A token is already saved. Leave blank to keep it, or paste a new one.";
      } else if (cfg.tokenUnreadable) {
        tokenHint.textContent = "Your saved token could not be decrypted on this computer. Paste it again.";
      }
    }
  } catch {
    /* keep the default */
  }
  urlEl.focus();
}

async function save() {
  errEl.textContent = "";
  saveBtn.disabled = true;
  try {
    const res = await window.fasttNative.saveConfig({
      serverUrl: urlEl.value,
      shareToken: tokenEl.value,
      ...advanced(),
      skipStartupSettings: skipEl.checked,
    });
    if (!res || !res.ok) {
      errEl.textContent = (res && res.error) || "Could not save settings.";
      saveBtn.disabled = false;
    }
    // On success the main process closes this window and loads the app.
  } catch (e) {
    errEl.textContent = "Unexpected error saving settings.";
    saveBtn.disabled = false;
  }
}

saveBtn.addEventListener("click", save);
quitBtn.addEventListener("click", () => window.fasttNative.quit());
restartBtn.addEventListener("click", () => window.fasttNative.restart(advanced()));
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter") save();
});

hydrate();
