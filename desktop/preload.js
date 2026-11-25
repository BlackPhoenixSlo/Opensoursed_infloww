"use strict";


const { contextBridge, ipcRenderer } = require("electron");

function readShellVersion() {
  const arg = process.argv.find((a) => a.startsWith("--infloww-rea-shell-version="));
  return arg ? arg.split("=")[1] : "unknown";
}

const str = (v) => (typeof v === "string" ? v : "");

try {
  // Least privilege: the remote page gets no Node/fs/arbitrary IPC, only narrow fixed calls; secrets never cross (Go live passes only the Creator id).
  contextBridge.exposeInMainWorld("fasttShell", Object.freeze({
    isDesktop: true,
    platform: process.platform,
    version: readShellVersion(),
    notify: (n) =>
      ipcRenderer.invoke("shell:notify", {
        id: str(n && n.id),
        title: str(n && n.title),
        body: str(n && n.body),
        href: str(n && n.href),
      }),
    openGoLive: (creatorId) => ipcRenderer.invoke("shell:open-go-live", String(creatorId == null ? "" : creatorId)),
  }));
} catch (err) {
  console.error("[preload] bridge failed:", err && err.message);
}

const CONNECT_ID = "infloww-rea-connect-of";

function makeConnectButton() {
  const btn = document.createElement("button");
  btn.id = CONNECT_ID;
  btn.type = "button";
  btn.textContent = "➕ Connect OnlyFans (app)";
  btn.title = "Add an OnlyFans account natively — no browser extension";
  Object.assign(btn.style, {
    padding: "11px 16px",
    borderRadius: "10px",
    border: "1px solid #6d5efc",
    background: "#6d5efc",
    color: "#fff",
    font: "600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    cursor: "pointer",
  });
  btn.addEventListener("mouseenter", () => (btn.style.background = "#7d70ff"));
  btn.addEventListener("mouseleave", () => (btn.style.background = "#6d5efc"));
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    ipcRenderer.invoke("shell:add-of-account");
  });
  return btn;
}

function extensionAnchor() {
  const els = document.querySelectorAll("button, a");
  for (const el of els) {
    if (/install chrome extension/i.test(el.textContent || "")) return el;
  }
  return null;
}

function syncConnectButton() {
  try {
    if (!document.body) return;
    const anchor = extensionAnchor();
    const existing = document.getElementById(CONNECT_ID);
    if (!anchor) {
      if (existing) existing.remove();
      return;
    }
    if (existing && document.contains(existing) && existing.previousSibling === anchor) return;
    if (existing) existing.remove();
    const btn = makeConnectButton();
    btn.style.margin = "0 0 0 10px";
    btn.style.verticalAlign = "middle";
    if (anchor.nextSibling) anchor.parentElement.insertBefore(btn, anchor.nextSibling);
    else anchor.parentElement.appendChild(btn);
  } catch (err) {
    console.error("[preload] connect button failed:", err && err.message);
  }
}

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", syncConnectButton);
} else {
  syncConnectButton();
}
setInterval(syncConnectButton, 2000);
