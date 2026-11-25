import { NOT_YET } from "@/lib/ofMirrorTooltip";

export interface Handoff {
  key: string;
  page: string;
  text: string;
  url: string;
  field?: string;
  live?: true;
  fieldLive?: true;
}

// Never send OF's /trust or copy a csrf: each hand-off opens OF's own page where the owner clicks OF's button.
const SPOTIFY = "https://onlyfans.com/my/settings/spotify";
const SPOTIFY_TEXT = "Sign in with spotify";
export const HANDOFFS: readonly Handoff[] = [
  { key: "settings--ethwallet-metamask", page: "settings/ethwallet", text: "https://metamask.io/download.html", url: "https://metamask.io/download.html" },
  { key: "settings--streaming-obs", page: "settings/streaming", text: "OBS", url: "https://obsproject.com/download", live: true },
  { key: "settings--streaming-chat-link", page: "settings/streaming", text: "https://onlyfans.com/my/streaming/chat", url: "https://onlyfans.com/my/streaming/chat", live: true },
  { key: "settings--streaming-obs-widgets", page: "settings/streaming", text: "https://obs-settings.onlyfans.com/", url: "https://obs-settings.onlyfans.com/", live: true },
  { key: "settings--account-google-sign-in", page: "settings/account/google", text: "Sign in with google", url: "https://onlyfans.com/my/settings/account/google", live: true },
  { key: "settings--account-x-sign-in", page: "settings/account/x", text: "Sign in with X", url: "https://onlyfans.com/my/settings/account/x", live: true },
  {
    key: "settings--account-connected-connect",
    page: "settings/account/connected",
    text: "Connect",
    url: "https://onlyfans.com/my/settings/account/connected",
    field: "#settings_connect_account",
    fieldLive: true,
  },
  { key: "settings--spotify-sign-in", page: "settings/spotify", text: SPOTIFY_TEXT, url: SPOTIFY, live: true },
  { key: "profile--spotify-sign-in", page: "profile/index", text: SPOTIFY_TEXT, url: SPOTIFY, live: true },
  { key: "profile--media-spotify-sign-in", page: "profile/media", text: SPOTIFY_TEXT, url: SPOTIFY, live: true },
  { key: "profile--state-more-menu-spotify-sign-in", page: "profile/state-more-menu", text: SPOTIFY_TEXT, url: SPOTIFY, live: true },
];

export const handoffsFor = (path: string): Handoff[] => HANDOFFS.filter((h) => h.page === path);

export function asHandoff(el: HTMLElement, url: string, drop: readonly string[] = []): HTMLAnchorElement {
  let a = el as HTMLAnchorElement;
  if (el.tagName !== "A") { // tagName, not instanceof: the frame's elements are of its own realm
    a = el.ownerDocument.createElement("a");
    for (const { name, value } of [...el.attributes]) if (!drop.includes(name)) a.setAttribute(name, value);
    a.append(...el.childNodes);
    el.replaceWith(a);
  }
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.removeAttribute("aria-disabled");
  a.setAttribute("data-oi-wired", "");
  return a;
}

export function bindHandoffs(doc: Document, path: string): () => void {
  const undos: (() => void)[] = [];
  for (const h of handoffsFor(path)) {
    const found = [...doc.querySelectorAll<HTMLElement>("#content a[href='#'], #content button")].find((e) => e.textContent?.trim() === h.text);
    if (!found) continue;
    const [rel, target, title] = [found.getAttribute("rel"), found.getAttribute("target"), found.getAttribute("title")];
    const a = asHandoff(found, h.url, ["disabled", "type"]);
    if (h.live) a.removeAttribute("title");
    else if (a !== found && !a.title) a.title = NOT_YET;
    if (a !== found) {
      undos.push(() => {
        found.append(...a.childNodes);
        a.replaceWith(found);
      });
    } else {
      undos.push(() => {
        if (title !== null) a.setAttribute("title", title);
        a.setAttribute("href", "#");
        if (rel === null) a.removeAttribute("rel");
        else a.rel = rel;
        if (target === null) a.removeAttribute("target");
        else a.target = target;
        a.setAttribute("aria-disabled", "true");
        a.removeAttribute("data-oi-wired");
      });
    }
    const field = h.field ? doc.querySelector<HTMLInputElement>(`#content ${h.field}`) : null;
    if (field) {
      const [disabled, readOnly, title] = [field.disabled, field.readOnly, field.getAttribute("title")];
      const box = field.closest<HTMLElement>(".v-input") ?? field;
      const open = (ev: Event) => {
        ev.preventDefault();
        a.click();
      };
      field.disabled = false;
      field.readOnly = true;
      field.setAttribute("data-oi-wired", "");
      if (h.fieldLive) field.removeAttribute("title");
      box.addEventListener("click", open);
      undos.push(() => {
        box.removeEventListener("click", open);
        if (title !== null) field.setAttribute("title", title);
        field.disabled = disabled;
        field.readOnly = readOnly;
        field.removeAttribute("data-oi-wired");
      });
    }
  }
  return () => {
    for (const undo of undos.reverse()) undo();
  };
}


export const HANDOFF_TITLE = "opens onlyfans.com";

export function reportHandoffUrl(place: "post", ids: { postId: string | number; username: string }): string;
export function reportHandoffUrl(place: "chat" | "message", ids: { fanId: string | number }): string;
export function reportHandoffUrl(place: "post" | "chat" | "message", ids: { postId?: string | number; username?: string; fanId?: string | number }): string {
  const e = (v: string | number | undefined) => encodeURIComponent(String(v));
  return place === "post" ? `https://onlyfans.com/${e(ids.postId)}/${e(ids.username)}` : `https://onlyfans.com/my/chats/chat/${e(ids.fanId)}/`;
}
