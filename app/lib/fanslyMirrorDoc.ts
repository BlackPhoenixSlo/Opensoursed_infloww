"use client";

import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";

import { useTheme } from "@/hooks/useTheme";
import { withCreator } from "@/lib/fansly-mirror-route";
import { proxyImage } from "@/lib/mediaUrl";
import { ofMeQuery, type OfMe } from "@/lib/ofMe";

export const FANSLY_LIGHT_CLASS = "bright-theme";
export const FANSLY_CHROME_STYLE_ID = "oi-fansly-chrome";
const FANSLY_CHROME_CSS = "[data-oi-nav]{display:none!important}.middle-side{margin-left:0!important}";

const PH = { username: "yourmodel", name: "Your Model" };
const PH_RE = new RegExp(`${PH.username}|${PH.name}`, "g");
const ATTRS = ["title", "alt", "aria-label", "placeholder"] as const;

type Me = Pick<OfMe, "username" | "name" | "avatar" | "header">;
type DocArgs = { dark: boolean } & ({ me: Me; accountId: string } | { me: null; accountId: string | null });

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

const origText = new WeakMap<Node, string>();
const origAttr = new WeakMap<Element, Map<string, string>>();

function setImage(el: HTMLElement, url: string) {
  if (el.localName === "img") el.setAttribute("src", url);
  else el.style.backgroundImage = `url("${url}")`;
}

export function prepareFanslyDoc(doc: Document, args: DocArgs): void {
  if (!doc.getElementById(FANSLY_CHROME_STYLE_ID)) {
    const style = doc.createElement("style");
    style.id = FANSLY_CHROME_STYLE_ID;
    style.textContent = FANSLY_CHROME_CSS;
    (doc.head ?? doc.documentElement).appendChild(style);
  }
  doc.documentElement.classList.toggle(FANSLY_LIGHT_CLASS, !args.dark);
  for (const a of doc.querySelectorAll('a[href^="/fansly-manager/"]')) a.setAttribute("href", withCreator(a.getAttribute("href")!, args.accountId));
  if (!args.me || !doc.body) return;
  const { me, accountId } = args;

  const username = str(me.username);
  const name = str(me.name);
  const swap = (t: string) => t.replace(PH_RE, (m) => (m === PH.username ? username : name) ?? m);
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = swap(origText.get(n) ?? n.nodeValue ?? "");
    if (t === n.nodeValue) continue;
    if (!origText.has(n)) origText.set(n, n.nodeValue ?? "");
    n.nodeValue = t;
  }
  for (const el of doc.body.querySelectorAll(ATTRS.map((a) => `[${a}]`).join(","))) {
    for (const attr of ATTRS) {
      const cur = el.getAttribute(attr);
      const v = origAttr.get(el)?.get(attr) ?? cur;
      if (v === null || swap(v) === cur) continue;
      let saved = origAttr.get(el);
      if (!saved) origAttr.set(el, (saved = new Map()));
      if (!saved.has(attr) && cur !== null) saved.set(attr, cur);
      el.setAttribute(attr, swap(v));
    }
  }
  const avatar = str(me.avatar);
  if (avatar) for (const el of doc.querySelectorAll<HTMLElement>("[data-oi-avatar]")) setImage(el, proxyImage(avatar, accountId));
  const header = str(me.header);
  if (header) for (const el of doc.querySelectorAll<HTMLElement>("[data-oi-banner]")) setImage(el, proxyImage(header, accountId));
}

export function onFanslyFrameReady(frame: HTMLIFrameElement, ready: (doc: Document) => void | (() => void)): () => void {
  let clean: void | (() => void);
  const onLoad = () => {
    clean?.();
    const doc = frame.contentDocument;
    clean = doc ? ready(doc) : undefined;
  };
  if (frame.contentDocument?.readyState === "complete") onLoad();
  frame.addEventListener("load", onLoad);
  return () => {
    frame.removeEventListener("load", onLoad);
    clean?.();
  };
}

export function useFanslyDoc(ref: RefObject<HTMLIFrameElement | null>, src: string, accountId: string | null): void {
  const me = useQuery(ofMeQuery(accountId)).data;
  const dark = useTheme().theme !== "light";
  useEffect(() => {
    const frame = ref.current;
    if (!frame) return;
    return onFanslyFrameReady(frame, (doc) => {
      if (doc.body) prepareFanslyDoc(doc, me && accountId ? { me, accountId, dark } : { me: null, accountId, dark });
    });
  }, [ref, src, accountId, me, dark]);
}
