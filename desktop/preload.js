"use strict";

// Preload for the REMOTE page (the hosted your-host.example.com UI).
//
// Least privilege: the remotely-served UI gets NO bridge into Node, the
// filesystem, or arbitrary IPC. We expose only a static, read-only version
// object (for a future shell↔UI handshake), AND — because the hosted Setup page
// can't know it's running inside the desktop app — we inject one native button
// that starts the OnlyFans capture flow. Its click handler lives here in the
// isolated preload world and calls a single no-argument IPC that just opens a
// login window (no data crosses, and the main process still checks the sender
// origin). One more narrow call: `notify({id, title, body, href})` hands four
// strings to the main process, which shows a native notification (lib/notify.js
// validates them; the web Notification permission never reached "granted" in
// packaged builds, cause unconfirmed). Badge and navigation hardening live in
// the main process, not here.

const { contextBridge, ipcRenderer } = require("electron");

function readShellVersion() {
  const arg = process.argv.find((a) => a.startsWith("--infloww-rea-shell-version="));
  return arg ? arg.split("=")[1] : "unknown";
}

const str = (v) => (typeof v === "string" ? v : "");

try {
  contextBridge.exposeInMainWorld("fasttShell", Object.freeze({
    isDesktop: true,
    platform: process.platform,
    version: readShellVersion(),
    // Resolves true when the OS notification was shown.
    notify: (n) =>
      ipcRenderer.invoke("shell:notify", {
        id: str(n && n.id),
        title: str(n && n.title),
        body: str(n && n.body),
        href: str(n && n.href),
      }),
  }));
} catch (err) {
  console.error("[preload] bridge failed:", err && err.message);
}

// ── Native "Connect OnlyFans" button injected into the hosted UI ─────────────
// So the account-capture flow is discoverable ON the page, not only in the macOS
// menu bar. On the Setup page it sits INLINE next to the "Install Chrome
// Extension" button (where you'd expect it); elsewhere it floats bottom-left.
// The click handler runs in this isolated preload context — never exposed to the
// page's own JavaScript.
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
    const anchor = extensionAnchor(); // present ONLY on the Setup page
    const existing = document.getElementById(CONNECT_ID);
    // Button lives ONLY on Setup, inline next to the extension button. Off Setup,
    // remove it (the Account menu is still available everywhere).
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
// Re-assert after SPA route changes (navigating to/from Setup moves the button).
setInterval(syncConnectButton, 2000);
