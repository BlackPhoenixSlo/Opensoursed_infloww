export function fmtCents(c: number | null | undefined): string {
  if (c == null || Number.isNaN(c)) return "—";
  const d = Math.round(Math.abs(c) / 100);
  return `${c < 0 && d > 0 ? "-" : ""}$${d.toLocaleString("en-US")}`;
}

export const isLoss = (c: number): boolean => fmtCents(c).startsWith("-");

export function fmtPrice(cents: number | null | undefined): string {
  if (cents == null || Number.isNaN(cents)) return "—";
  const c = Math.sign(cents) * Math.round(Math.abs(cents));
  const digits = c % 100 === 0 ? 0 : 2;
  const s = (Math.abs(c) / 100).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${c < 0 ? "-" : ""}$${s}`;
}

export function fmtCentsBlankZero(c: number | null | undefined): string {
  if (c == null || c === 0 || Number.isNaN(c)) return "—";
  return fmtCents(c);
}

export function dollarsToCents(raw: string): number | null {
  const n = Number(raw);
  return raw.trim() === "" || !Number.isFinite(n) || n < 0 ? null : Math.round(n * 100);
}

export function fmtSpend(cents: number): string {
  const dollars = Math.round(cents / 100);
  return dollars > 9_999 ? `$${Math.round(dollars / 100) / 10}k` : `$${dollars.toLocaleString("en-US")}`;
}

export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString();
}

export function fmtDuration(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = String(Math.floor(sec % 60)).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function fmtReplyTime(sec: number | null): string {
  if (sec == null) return "—";
  const s = Math.round(sec);
  if (s < 60) return `${s}s`;
  const two = (n: number) => String(n).padStart(2, "0");
  if (s < 3600) return `${Math.floor(s / 60)}m ${two(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${two(Math.floor((s % 3600) / 60))}m`;
}

export interface Growth { text: string; dir: "up" | "down" | null }
export function growthOf(cur: number, prev: number | null | undefined): Growth {
  if (prev == null || !(prev > 0)) return { text: "-", dir: null };
  if (cur === prev) return { text: "0.00%", dir: null };
  const g = (cur - prev) / prev;
  const text = Math.abs(g * 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%";
  return { text, dir: g > 0 ? "up" : "down" };
}

export function fmtAgo(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return null;
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 0) return "soon";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

export function parseUtc(s: string | null | undefined): Date | null {
  if (!s) return null;
  // The relay writes zone-less utcnow() stamps: read them as UTC, not the browser's zone.
  const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(s);
  const d = new Date(naive ? `${s.replace(" ", "T")}Z` : s);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDateShort(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function localWhen(iso: string): string {
  const d = new Date(iso);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const city = (tz.split("/").pop() ?? tz).replace(/_/g, " ");
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${day} ${time} (${city})`;
}

export function fmtTimeOnly(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function clockTime(d: Date): string {
  return CLOCK.format(d).toLowerCase();
}
const CLOCK = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });

export function rosterUnreadText(unread: number): string {
  return unread > 99 ? "99+" : String(unread);
}
