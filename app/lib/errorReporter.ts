"use client";


import { relay } from "./relay";

interface ReportPayload {
  source: "browser";
  kind: string;
  message: string;
  stack?: string;
  url?: string;
  user_agent?: string;
  context?: Record<string, unknown>;
}

const DEDUPE_WINDOW_MS = 30_000;
const _recent = new Map<string, number>();

function dedupeKey(p: ReportPayload): string {
  const head = (p.stack || "").split("\n").slice(0, 2).join("\n");
  return `${p.kind}::${p.message}::${head}`;
}

export function reportError(
  err: unknown,
  kind = "error",
  extra?: Record<string, unknown>,
): void {
  if (typeof window === "undefined") return;
  let message = "(unknown error)";
  let stack: string | undefined;
  if (err instanceof Error) {
    message = err.message || err.name || message;
    stack = err.stack;
  } else if (typeof err === "string") {
    message = err;
  } else if (err && typeof err === "object") {
    try { message = JSON.stringify(err).slice(0, 2000); } catch { }
  }

  const payload: ReportPayload = {
    source: "browser",
    kind,
    message: message.slice(0, 4000),
    stack,
    url: window.location.href,
    user_agent: navigator.userAgent,
    context: extra,
  };

  if (shouldSkip(payload.message) || shouldSkip(payload.stack || "")) return;

  const key = dedupeKey(payload);
  const now = Date.now();
  const prev = _recent.get(key);
  if (prev && now - prev < DEDUPE_WINDOW_MS) return;
  _recent.set(key, now);

  relay.post("/admin/errors", payload).catch((postErr: unknown) => {
    console.warn("[errorReporter] failed to POST", postErr);
  });
}

// Network-layer failures (incl. our own POST) must never be reported: relay slow -> fetch fails -> report -> relay slower.
const _SKIP_PATTERNS = [
  "ECONNRESET",
  "socket hang up",
  "Failed to fetch",
  "Failed to proxy",
  "NetworkError",
  "Load failed",
  "/admin/errors",
];

function shouldSkip(message: string): boolean {
  return _SKIP_PATTERNS.some((p) => message.includes(p));
}

let _installed = false;

// Deliberately does not patch console.error: that looped POSTs to /admin/errors when the relay was under load.
export function installGlobalErrorHandlers(): void {
  if (typeof window === "undefined" || _installed) return;
  _installed = true;

  window.addEventListener("error", (event) => {
    if (!event.error) return;
    const msg = String(event.error?.message ?? event.error);
    if (shouldSkip(msg)) return;
    reportError(event.error, "window-error", {
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    const msg = String(reason?.message ?? reason);
    if (shouldSkip(msg)) return;
    reportError(reason, "unhandled-rejection");
  });
}
