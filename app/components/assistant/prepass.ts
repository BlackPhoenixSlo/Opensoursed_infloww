import {
  isDivider, isGroup, SETTINGS_TABS, SIDEBAR, SIDEBAR_FOOTER, visibleLinks, visibleSidebar,
  type NavFilter, type NavLink,
} from "@/lib/nav";

export type PrepassHit =
  | { kind: "navigate"; href: string; label: string }
  | { kind: "theme"; theme: "light" | "dark" | "toggle" }
  | { kind: "chat"; handle: string };

const norm = (s: string): string =>
  s.toLowerCase().replace(/[^a-z0-9&'\s-]/g, " ").replace(/\s+/g, " ").trim();

const QUESTION_RE = /^(?:how|what|where|why|when|who|which|whats|can|could|should|would|is|are|do|does|did|will|may)\b/;
const NAV_RE =
  /^(?:open|go to|goto|show me|show|take me to|switch to|navigate to|bring up|jump to)\s+(?:the\s+|my\s+)?(.+?)(?:\s+(?:page|tab|screen|section))?$/;
const THEME_RE =
  /^(?:(?:switch|turn|change|go|set|use|enable)\s+(?:on\s+|to\s+)?)?(?:the\s+)?(dark|light)\s+(?:mode|theme)(?:\s+on)?$/;
const TOGGLE_RE = /^(?:toggle|switch|flip|change)\s+(?:the\s+)?(?:theme|dark mode|light mode)$/;
const CHAT_RE =
  /^(?:open|chat with|message|dm|go to)\s+(?:(?:the\s+)?chat\s+(?:with\s+)?)?@([a-z0-9_.-]{1,64})(?:'s\s+chat|\s+chat)?$/;

export const canOpenChats = (links: readonly NavLink[]): boolean => links.some((l) => l.href === "/messages-pro");

export function prepass(raw: string, links: readonly NavLink[]): PrepassHit | null {
  if (raw.includes("?") || raw.includes("\n")) return null;
  const t = raw
    .trim()
    .toLowerCase()
    .replace(/[.!]+$/, "")
    .replace(/^please\s+|,?\s+please$/g, "")
    .trim();
  if (!t || QUESTION_RE.test(t)) return null;

  const theme = THEME_RE.exec(t);
  if (theme) return { kind: "theme", theme: theme[1] as "dark" | "light" };
  if (TOGGLE_RE.test(t)) return { kind: "theme", theme: "toggle" };

  const chat = CHAT_RE.exec(t);
  if (chat && canOpenChats(links)) {
    const typed = /@([A-Za-z0-9_.-]{1,64})/.exec(raw);
    return { kind: "chat", handle: typed ? typed[1] : chat[1] };
  }

  const nav = NAV_RE.exec(t);
  if (!nav) return null;
  const want = norm(nav[1]);
  const hit = links.find((l) => norm(l.label) === want);
  return hit ? { kind: "navigate", href: hit.href, label: hit.label } : null;
}

const SETTINGS_LANDING = "/settings/account";

export function commandLinks(f: NavFilter): NavLink[] {
  const side = visibleSidebar(SIDEBAR, f).flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
  const tabs = visibleLinks(SETTINGS_TABS, f);
  const lands = tabs.some((t) => t.href === SETTINGS_LANDING) ? "/settings" : tabs[0]?.href;
  const footer = visibleLinks(SIDEBAR_FOOTER, f).flatMap((l) =>
    l.href !== "/settings" ? [l] : lands ? [{ ...l, href: lands }] : []);
  return [...side, ...footer, ...tabs];
}

export function openablePages(f: NavFilter): ReadonlySet<string> {
  const pages = new Set(commandLinks(f).map((l) => l.href));
  const all = SIDEBAR.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
  for (const l of all) {
    if (l.tabOf && pages.has(l.tabOf) && visibleLinks([{ ...l, tabOf: undefined }], f).length > 0) pages.add(l.href);
  }
  return pages;
}

export function confirmation(hit: PrepassHit, theme?: "light" | "dark"): string {
  if (hit.kind === "navigate") return `Opened ${hit.label}.`;
  if (hit.kind === "chat") return `Opened @${hit.handle}'s chat.`;
  return `Switched to ${theme ?? hit.theme} mode.`;
}
