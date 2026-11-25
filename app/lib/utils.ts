import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function decodeHtmlEntities(s: string | null | undefined): string {
  if (!s) return "";
  return s
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'");
}

export function fmtRelTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diffMs = d.getTime() - Date.now();
  const future = diffMs > 0;
  const sec = Math.floor(Math.abs(diffMs) / 1000);
  const fmt = (n: number, unit: string) =>
    future ? `in ${n}${unit}` : `${n}${unit} ago`;
  if (sec < 60) return future ? "in <1m" : "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return fmt(min, "m");
  const hr = Math.floor(min / 60);
  if (hr < 24) return fmt(hr, "h");
  const day = Math.floor(hr / 24);
  if (day < 30) return fmt(day, "d");
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function describeDeadSession(reason: string | null | undefined): string {
  if (reason === "wrong_user") {
    return "OnlyFans rejected this login — the creator logged in elsewhere or " +
      "unlinked it. Automations stay paused until it is re-linked in Manage creators.";
  }
  if (reason === "otp_required") {
    return "OnlyFans wants a 2FA code for this login. Automations stay paused until it " +
      "is signed in again with Browserbase login in Manage creators, which takes the code.";
  }
  if (reason === "no_session") {
    return "No captured session for this account on this host. Automations stay " +
      "paused until the session is captured in Manage creators.";
  }
  return "This account's OnlyFans session is not working. Automations stay " +
    "paused until it is re-captured in Manage creators.";
}

export interface SubStatusDisplay {
  short: string;
  tone: "ok" | "warn" | "err" | "fg-dim";
  long: string;
  expired: boolean;
}

export function interpretSubStatus(
  rawStatus: string | null | undefined,
  expiredAtIso: string | null | undefined,
  nowMs: number = Date.now(),
): SubStatusDisplay {
  const expiry = expiredAtIso ? new Date(expiredAtIso) : null;
  const expired = !!(expiry && !Number.isNaN(expiry.getTime()) && expiry.getTime() < nowMs);
  const status = (rawStatus || "").toLowerCase();
  if (expired) {
    return {
      short: "Expired",
      tone: "err",
      long: expiredAtIso ? `Expired ${fmtRelTime(expiredAtIso)}` : "Expired",
      expired: true,
    };
  }
  if (!rawStatus) {
    return { short: "—", tone: "fg-dim", long: "—", expired: false };
  }
  if (status === "active") {
    return {
      short: "Active",
      tone: "ok",
      long: expiredAtIso ? `Active · renews ${fmtRelTime(expiredAtIso)}` : "Active",
      expired: false,
    };
  }
  if (status.includes("expire")) {
    return {
      short: "Won't renew",
      tone: "warn",
      long: expiredAtIso ? `Won't renew · ends ${fmtRelTime(expiredAtIso)}` : "Won't renew",
      expired: false,
    };
  }
  return { short: rawStatus, tone: "fg-dim", long: rawStatus, expired: false };
}
