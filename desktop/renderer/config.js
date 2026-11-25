"use strict";


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
  document.getElementById("intro").hidden = true;
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
