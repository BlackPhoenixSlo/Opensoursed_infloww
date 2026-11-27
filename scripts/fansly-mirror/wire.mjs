export function chartPlaceholders(doc) {
  const canvases = [...doc.getElementsByTagName("canvas")];
  for (const c of canvases) {
    const div = doc.createElement("div");
    for (const { name, value } of c.attributes) if (name !== "width" && name !== "height") div.setAttribute(name, value);
    const size = (n, d) => (/^\d+$/.test(c.getAttribute(n) || "") ? c.getAttribute(n) : d);
    if (!div.hasAttribute("style")) div.setAttribute("style", `width:${size("width", 300)}px;height:${size("height", 150)}px`);
    div.setAttribute("data-oi-chart-placeholder", "");
    c.replaceWith(div);
  }
  return canvases.length;
}

export const THEME_MARKER = "bright-theme";
export const BOOT_TEXT = `try{if(parent!==window)if(parent.document.documentElement.getAttribute("data-theme")!=="light")document.documentElement.classList.remove("${THEME_MARKER}")}catch(e){}`;
const OVERRIDES = ".oi-state-link{position:absolute;top:0;right:0;bottom:0;left:0;z-index:3}.oi-state-backdrop{position:fixed;top:0;right:0;bottom:0;left:0;z-index:1}:has(> .oi-state-link){position:relative}.back-drop:has(> .oi-state-backdrop){isolation:isolate}.back-drop > .oi-state-backdrop{z-index:-1}[data-oi-chart-placeholder]{display:block;background:rgba(128,128,128,.12)}.transparent-dropdown:focus-within > .dropdown-list,.balance-dropdown:focus-within > .dropdown-list{display:flex!important;z-index:5}.user-account:hover .user-account-dropdown,.user-account:focus-within .user-account-dropdown{display:flex}";

export const isBoot = (el) => el.localName === "script" && !el.attributes.length && el.textContent === BOOT_TEXT && el.parentNode?.localName === "head";

export function addChrome(doc) {
  const head = doc.head;
  const boot = doc.createElement("script");
  boot.textContent = BOOT_TEXT;
  const charset = head.querySelector(":scope > meta[charset]");
  if (charset) charset.after(boot);
  else head.prepend(boot);
  const style = doc.createElement("style");
  style.id = "fansly-mirror-overrides";
  style.textContent = OVERRIDES;
  head.append(style);
}

const IDENT = "-?[_a-zA-Z][\\w-]*";
const SIMPLE = `(?:#${IDENT}|\\.${IDENT}|\\[${IDENT}(?:\\*?=(?:${IDENT}|"[^"\\\\]*"))?\\]|:nth-child\\(\\d+\\))`;
const BASE = `(?:[a-zA-Z][\\w-]*${SIMPLE}*|${SIMPLE}+)`;
const COMPOUND = `${BASE}(?::has\\((?:> )?${BASE}\\))?`;
export const OPENER_FORM = new RegExp(`^${COMPOUND}(?:(?: | > )${COMPOUND})*$`);
const CLOSE = /^(?:close|cancel|×|done)$/i;
const HTML_NS = "http://www.w3.org/1999/xhtml";
const NO_CHILDREN = new Set(["img", "input", "br", "hr", "wbr", "col", "textarea", "select"]);

export function stateWires(parentDoc, stateDoc, opener, toState, toParent) {
  const open = parentDoc.querySelector(opener);
  if (!open) return null;
  const overlay = stateDoc.querySelector(".cdk-overlay-container") || stateDoc.body;
  const isClose = (b) => CLOSE.test(b.textContent.trim()) || CLOSE.test((b.getAttribute("aria-label") || "").trim());
  const toggle = stateDoc.querySelector(opener);
  const closes = [...overlay.querySelectorAll("button, [role=button]")].filter((b) => b !== toggle && isClose(b));
  return {
    parent: [[open, "oi-state-link", toState, "Open"]],
    state: [
      [stateDoc.querySelector(".cdk-overlay-backdrop, .back-drop") || stateDoc.body, "oi-state-backdrop", toParent, "Close"],
      ...(toggle ? [[toggle, "oi-state-link", toParent, "Toggle"]] : []),
      ...closes.map((el) => [el, "oi-state-link", toParent, "Close"]),
    ],
  };
}

export function siblingWires(states) {
  for (const o of states)
    for (const s of states) {
      const el = s !== o && s.parent === o.parent && o.doc.querySelector(s.opener);
      if (el && !o.wires.some(([w, cls]) => cls !== "oi-state-backdrop" && (w.closest("a") || w).contains(el))) o.wires.push([el, "oi-state-link", s.href, "Open"]);
    }
}

export function addWires(list) {
  for (const [el, cls, href, label] of list) {
    const anchor = el.closest("a");
    if (anchor) {
      anchor.setAttribute("href", href);
      anchor.setAttribute("target", "_top");
      continue;
    }
    let host = el;
    while (host.parentNode?.nodeType === 1 && (host.namespaceURI !== HTML_NS || NO_CHILDREN.has(host.localName))) host = host.parentNode;
    const a = el.ownerDocument.createElement("a");
    for (const [k, v] of [["class", cls], ["href", href], ["target", "_top"], ["aria-label", label]]) a.setAttribute(k, v);
    host.prepend(a);
  }
}

const AVATAR_HOOK = ".user-avatar, .creator-avatar, .default-avatar";
const BANNER_HOOK = ".profile-banner, .profile-banner-image, .default-banner";
const RAIL_HOOK = ".left-side, .side-bar-wrapper";
const TOP_BAR_HOOK = "app-nav-bar-top";
const imageOf = (el) => (el.localName === "img" ? el : el.querySelector("img") || el);
const classWord = (el, ws) => [...el.classList].some((c) => ws.some((w) => `-${c.toLowerCase().replace(/_/g, "-")}-`.includes(`-${w}-`)));

export function tagHooks(doc, { profileRoot, names }) {
  const naming = (el) => ["alt", "title", "src"].some((a) => names.some((n) => (el.getAttribute(a) || "").toLowerCase().includes(n)));
  const rail = doc.querySelector(RAIL_HOOK) || doc.querySelector("nav, [role=navigation]");
  const hooked = [...doc.querySelectorAll(AVATAR_HOOK)].map(imageOf);
  const header = hooked.find((el) => !rail?.contains(el) && !el.closest(TOP_BAR_HOOK));
  let avatars = hooked.filter(naming).concat(profileRoot && header ? [header] : []);
  if (!avatars.length) avatars = [...doc.querySelectorAll("img")].filter(naming);
  for (const el of avatars) el.setAttribute("data-oi-avatar", "");
  const banner = profileRoot && (doc.querySelector(BANNER_HOOK) || [...doc.body.querySelectorAll("[class]")].find((el) => classWord(el, ["banner", "cover"])));
  if (banner) imageOf(banner).setAttribute("data-oi-banner", "");
  if (rail) rail.setAttribute("data-oi-nav", "");
  return { avatar: avatars.length > 0, banner: Boolean(banner), rail: Boolean(rail) };
}
