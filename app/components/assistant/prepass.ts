/**
 * prepass — the composer's deterministic commands (spec D12), run before any
 * LLM call in both Q&A and do-mode.
 *
 * "open settings", "dark mode", "chat with @lena" need no model: the words name
 * the thing. An imperative verb plus a page label the session may see
 * (`visibleLinks`) navigates; the theme words set the theme; "open/chat with
 * @handle" opens that fan's chat when the session may open Messages Pro
 * (`canOpenChats`), else it goes on to the LLM. Anything else — a question above all ("how do
 * I open settings?") — returns null and goes to the LLM unchanged.
 *
 * Pure: the caller passes the visible links and runs the hit.
 */

import {
  isDivider, isGroup, SETTINGS_TABS, SIDEBAR, SIDEBAR_FOOTER, visibleLinks, visibleSidebar,
  type NavFilter, type NavLink,
} from "@/lib/nav";

export type PrepassHit =
  | { kind: "navigate"; href: string; label: string }
  | { kind: "theme"; theme: "light" | "dark" | "toggle" }
  | { kind: "chat"; handle: string };

/** Lowercase, drop emoji/punctuation, collapse runs (answerLinks' `norm`). */
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

/** The session may open a fan's chat: Messages Pro is among its pages. */
export const canOpenChats = (links: readonly NavLink[]): boolean => links.some((l) => l.href === "/messages-pro");

/** The command `raw` names, or null to send it on. */
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
    // The handle as typed (OF handles are case-insensitive, but keep it).
    const typed = /@([A-Za-z0-9_.-]{1,64})/.exec(raw);
    return { kind: "chat", handle: typed ? typed[1] : chat[1] };
  }

  const nav = NAV_RE.exec(t);
  if (!nav) return null;
  const want = norm(nav[1]);
  // A placeholder page is never a destination (Fansly's own "Settings").
  const hit = links.find((l) => !l.notBuilt && norm(l.label) === want);
  return hit ? { kind: "navigate", href: hit.href, label: hit.label } : null;
}

/** The pages a command may open: the sidebar, footer and Settings tabs as
 *  this session sees them (a hidden group hides its pages too). */
export function commandLinks(f: NavFilter): NavLink[] {
  const side = visibleSidebar(SIDEBAR, f).flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
  return [...side, ...visibleLinks(SIDEBAR_FOOTER, f), ...visibleLinks(SETTINGS_TABS, f)];
}

/** The thread's confirmation line for a hit that ran. */
export function confirmation(hit: PrepassHit, theme?: "light" | "dark"): string {
  if (hit.kind === "navigate") return `Opened ${hit.label}.`;
  if (hit.kind === "chat") return `Opened @${hit.handle}'s chat.`;
  return `Switched to ${theme ?? hit.theme} mode.`;
}
