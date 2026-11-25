"use client";


const SW_URL = "/sw-images.js";

export function swEnabled(): boolean {
  return process.env.NODE_ENV === "production";
}

export function registerImageSW(): void {
  if (typeof window === "undefined") return;
  if (!swEnabled()) return;
  if (!("serviceWorker" in navigator)) return;

  const proto = window.location.protocol;
  const host = window.location.hostname;
  const isLocalhost = host === "localhost" || host === "127.0.0.1";
  if (proto !== "https:" && !isLocalhost) {
    console.info("[sw] not registering — insecure origin");
    return;
  }

  navigator.serviceWorker
    .register(SW_URL, { scope: "/" })
    .then(async (reg) => {
      try { await reg.update(); } catch { }
    })
    .catch((err) => {
      console.warn("[sw] register failed", err);
    });
}
