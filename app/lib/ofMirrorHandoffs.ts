/**
 * Phase 3's hand-off table (docs/spec/ofm-not-yet/phase-03-settings-privacy-links.md, Interfaces › Hand-off): each
 * outbound link on an OF settings page that opens OnlyFans's or the provider's own page in a new tab and sends nothing
 * through the Relay. The URLs live here, never in a committed page, so the generator's leak guard still scrubs external
 * hosts there (ADR-0006); this table is the one place to correct one. bindHandoffs (mounted by bindWrites, both scopes)
 * turns each entry's captured `href="#"` anchor (or disabled button, swapped for an anchor with its classes and content)
 * into a live one, as the Bank note's link (`bankNote`, ofMirrorWrites).
 * The Not-yet title stays until the control's Live-proof pass (D1); an entry marked `live` has passed and drops it.
 *
 * Ticket 58 r10 (capture-checklist row 10 `settings--handoff-pages`, measured 2026-11-21): OF's Sign in with X and
 * Google send an aborted POST /api2/v2/trust and then a csrf-bound OF URL that 302s to OF's own page; Spotify's goes
 * through OF's csrf-bound proxy to Spotify. We never send /trust and never copy a csrf: each hands off to the OF page
 * where the owner clicks OF's own button. Connected accounts' Connect is an in-app write on OF (POST /users/connect
 * {login}); not built (no captured undo), its field and button hand off to OF's page. Spring Store's "here" stays
 * parked: absent from OF's build (ticket 71). NFT's Connect keeps OnlyFans's own disable.
 * Ticket 110: Bank's "Add card", "Add a payment card" and "Add funds to your wallet" open OnlyFans's own pages too:
 * row 10 measured 2026-11-21 did not record Add card / Add a payment card / Add funds;
 * parked — needs capture (re-sitting of row 10).
 */

import { NOT_YET } from "@/lib/ofMirrorTooltip";

export interface Handoff {
  /** The control's id, its capture record's (`<section>--<control-slug>`). */
  key: string;
  /** Its page, the path under of-mirror/pages. */
  page: string;
  /** The captured anchor's or button's text in the page's content column. */
  text: string;
  url: string;
  /** A form field that opens the same hand-off when clicked (readonly, Wired), e.g. Connected accounts' username. */
  field?: string;
  /** Its Live proof passed (its capture record's `proof.verdict: pass`, D1): the Not-yet title drops. */
  live?: true;
  /** The same for `field` (its own capture record, e.g. settings--account-connected-username). */
  fieldLive?: true;
}

/**
 * Where each URL comes from: the three OnlyFans/MetaMask addresses are OnlyFans's own link text on the captured page;
 * OBS's is OBS's public download page (the captured href was scrubbed to "#"). Ticket 58 r10: X, Google and Connected
 * accounts' are OF's own pages, measured r10 (the 302 targets and the Account page's links). Spotify's is OF's own
 * Spotify settings page: `inferred` — the page is measured to exist (settings/spotify, in the sitting); that OF's
 * button there runs the OAuth is the record's (OF's proxy URL needs a session csrf, so it is never reproduced here).
 */
const SPOTIFY = "https://onlyfans.com/my/settings/spotify"; // inferred (see above)
const SPOTIFY_TEXT = "Sign in with spotify";
export const HANDOFFS: readonly Handoff[] = [
  { key: "settings--ethwallet-metamask", page: "settings/ethwallet", text: "https://metamask.io/download.html", url: "https://metamask.io/download.html" },
  // Live proofs passed 2026-11-21 (docs/of-manager/captures/settings--streaming-{obs,chat-link,obs-widgets}.json): title dropped (D1).
  { key: "settings--streaming-obs", page: "settings/streaming", text: "OBS", url: "https://obsproject.com/download", live: true },
  { key: "settings--streaming-chat-link", page: "settings/streaming", text: "https://onlyfans.com/my/streaming/chat", url: "https://onlyfans.com/my/streaming/chat", live: true },
  { key: "settings--streaming-obs-widgets", page: "settings/streaming", text: "https://obs-settings.onlyfans.com/", url: "https://obs-settings.onlyfans.com/", live: true },
  // ticket 58 r10: measured OF pages (never /trust, never a csrf). Live proofs passed 2026-11-21 (`live`, `fieldLive`:
  // their docs/of-manager/captures/<key>.json and settings--account-connected-username.json); Connect is still
  // parked, its title kept (D1).
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

/** The table's entries for the Mirror page at `path`. */
export const handoffsFor = (path: string): Handoff[] => HANDOFFS.filter((h) => h.page === path);

/**
 * Each hand-off control on `path` in `doc` opens its URL in a new tab, `noopener noreferrer`, Wired, title kept until
 * its Live pass (D1; a `live` entry's title dropped):
 * a captured `href="#"` anchor is wired in place; a disabled button is swapped for an anchor with its classes and
 * content; an entry's `field` turns readonly and Wired, and a click on it (or its label) opens the same tab.
 * Returns its undo.
 */
export function bindHandoffs(doc: Document, path: string): () => void {
  const undos: (() => void)[] = [];
  for (const h of handoffsFor(path)) {
    const found = [...doc.querySelectorAll<HTMLElement>("#content a[href='#'], #content button")].find((e) => e.textContent?.trim() === h.text);
    if (!found) continue;
    let a: HTMLAnchorElement;
    if (found.tagName === "BUTTON") {  // not instanceof: the frame's elements are of its own realm
      a = doc.createElement("a");
      for (const { name, value } of [...found.attributes]) if (name !== "disabled" && name !== "type") a.setAttribute(name, value);
      if (h.live) a.removeAttribute("title");
      else if (!a.title) a.title = NOT_YET;
      a.append(...found.childNodes);
      found.replaceWith(a);
      undos.push(() => {
        found.append(...a.childNodes);
        a.replaceWith(found);
      });
    } else {
      a = found as HTMLAnchorElement;
      const [rel, target, title] = [a.getAttribute("rel"), a.getAttribute("target"), a.getAttribute("title")];
      if (h.live) a.removeAttribute("title");
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
    a.href = h.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.removeAttribute("aria-disabled");
    a.setAttribute("data-oi-wired", "");
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
