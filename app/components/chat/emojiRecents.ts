import { QUICK_EMOJIS } from "./emojiData";

const LS_RECENTS_KEY = "chatterly:emoji_recents";
const MAX_RECENTS = 24;
// The native `storage` event fires only on other tabs, so same-tab listeners need our own event.
const RECENTS_EVENT = "chatterly:emoji_recents:changed";

function loadRecents(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LS_RECENTS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.slice(0, MAX_RECENTS).filter((s) => typeof s === "string") : [];
  } catch { return []; }
}

function pushRecent(emoji: string) {
  if (typeof window === "undefined") return;
  try {
    const cur = loadRecents();
    const next = [emoji, ...cur.filter((e) => e !== emoji)].slice(0, MAX_RECENTS);
    window.localStorage.setItem(LS_RECENTS_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent(RECENTS_EVENT));
  } catch { }
}

function subscribeRecents(cb: () => void): () => void {
  window.addEventListener(RECENTS_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(RECENTS_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

function buildQuickRow(recents: string[], slots: number): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const e of recents) {
    if (out.length >= slots) break;
    if (seen.has(e)) continue;
    seen.add(e);
    out.push(e);
  }
  for (const e of QUICK_EMOJIS) {
    if (out.length >= slots) break;
    if (seen.has(e)) continue;
    seen.add(e);
    out.push(e);
  }
  return out;
}

export { LS_RECENTS_KEY, buildQuickRow, loadRecents, pushRecent, subscribeRecents };
