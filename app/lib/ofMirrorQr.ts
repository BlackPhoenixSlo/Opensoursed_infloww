"use client";


import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { proxyImage } from "@/lib/mediaUrl";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { relay } from "@/lib/relay";
import QRCode from "@/lib/vendor/qrcode-svg";

export const QR_PAGE = "settings/qrcode";
const HOST = "onlyfans.com";
const BOX = 66;
const MARK = 54;
const DOT = 6;
const START = 246;
const EXPORT_WIDTH = 738;

const logo = (x: number) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${MARK}" height="${MARK}" viewBox="0 0 400 400" x="${x}" y="${x}">` +
  '<path fill="#00aeef" d="M137.5 75a125 125 0 10125 125 125 125 0 00-125-125zm0 162.5A37.5 37.5 0 11175 200a37.45 37.45 0 01-37.5 37.5z"/>' +
  '<path fill="#008ccf" d="M278 168.75c31.76 9.14 69.25 0 69.25 0-10.88 47.5-45.38 77.25-95.13 80.87A124.73 124.73 0 01137.5 325L175 205.81C213.55 83.3 233.31 75 324.73 75h62.77c-10.5 46.25-46.69 81.58-109.5 93.75z"/>' +
  "</svg>";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export interface QrInput {
  username: string;
  avatar: string | null;
  showUrl: boolean;
  measure?: (text: string, size: number) => number;
}
export interface Qr {
  svg: string;
  width: number;
  height: number;
}

export function qrSize(username: string): { size: number; code: QRCode } {
  const content = `https://${HOST}/${username}?qr=1`;
  let size = START;
  for (;;) {
    const code = new QRCode({ content, ecl: "H", width: size, height: size, join: true });
    const next = (code.qrcode.modules.length + 8) * DOT;
    if (next === size) return { size, code };
    size = next;
  }
}

export function drawQr({ username, avatar, showUrl, measure }: QrInput): Qr {
  const { size: t, code } = qrSize(username);
  const qr = code.svg().replace(/^<\?xml[^>]*>\s*/, "");
  const at = (t - BOX) / 2;
  const mark = (t - MARK) / 2;
  let height = t;
  let defs = "";
  let text = "";
  if (showUrl) {
    const label = `${HOST}/${username}`;
    let font = (16 * t) / START;
    const w = measure?.(label, font);
    if (w && w > t - 48) font = (font * (t - 48)) / w;
    const h = Math.round(font * 1.172 * 100) / 100;
    const y = Math.round((t - 12 + font * 0.928) * 100) / 100;
    text = `<text font-family="Roboto, sans-serif" font-size="${font}" fill="#000000" text-anchor="middle" x="${t / 2}" y="${y}">${esc(label)}</text>`;
    height = t + h;
    defs += "<style>@import url(https://fonts.googleapis.com/css2?family=Roboto&amp;display=swap)</style>";
  }
  let middle = logo(mark);
  if (avatar) {
    defs += `<clipPath id="oi-qr-avatar"><circle r="${MARK / 2}" cx="${t / 2}" cy="${t / 2}" fill="#ffffff"/></clipPath>`;
    middle = `<image width="${MARK}" height="${MARK}" x="${mark}" y="${mark}" href="${esc(avatar)}" clip-path="url(#oi-qr-avatar)"/>`;
  }
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" version="1.1" xmlns:xlink="http://www.w3.org/1999/xlink" width="${t}" height="${height}">` +
    (defs ? `<defs>${defs}</defs>` : "") +
    `<rect width="${t}" height="${height}" fill="#ffffff"/>` +
    qr +
    `<rect width="${BOX}" height="${BOX}" x="${at}" y="${at}" fill="#ffffff" shape-rendering="crispEdges"/>` +
    middle +
    text +
    "</svg>";
  return { svg, width: t, height };
}

export const qrSrc = (svg: string) => `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;

export const exportSize = (qr: { width: number; height: number }) => ({ width: EXPORT_WIDTH, height: (EXPORT_WIDTH * qr.height) / qr.width });

const PREF = { url: "of-mirror:QR_CODE_URL", avatar: "of-mirror:QR_CODE_AVATAR" } as const;
const getPref = (k: keyof typeof PREF) => {
  try {
    return localStorage.getItem(PREF[k]) === "true";
  } catch {
    return false;
  }
};
const setPref = (k: keyof typeof PREF, v: boolean) => {
  try {
    localStorage.setItem(PREF[k], String(v));
  } catch {
  }
};

function cropAvatar(doc: Document, url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = doc.createElement("img");
    img.onload = () => {
      try {
        const side = Math.min(img.naturalWidth, img.naturalHeight);
        const out = Math.min(side, 162);
        const canvas = doc.createElement("canvas");
        canvas.width = canvas.height = out;
        const ctx = canvas.getContext("2d");
        if (!ctx || !side) return reject(new Error("no canvas"));
        ctx.drawImage(img, (-(img.naturalWidth - side) * out) / (2 * side), (-(img.naturalHeight - side) * out) / (2 * side), (img.naturalWidth * out) / side, (img.naturalHeight * out) / side);
        resolve(canvas.toDataURL());
      } catch (e) {
        reject(e);
      }
    };
    img.onerror = () => reject(new Error("avatar failed to load"));
    img.src = url;
  });
}

export function downloadQr(doc: Document, qr: Qr & { src: string }, username: string): void {
  const img = doc.createElement("img");
  img.onload = () => {
    const { width, height } = exportSize(qr);
    const canvas = doc.createElement("canvas");
    canvas.setAttribute("width", String(width));
    canvas.setAttribute("height", String(height));
    canvas.getContext("2d")?.drawImage(img, 0, 0, width, height);
    const a = doc.createElement("a");
    a.href = canvas.toDataURL();
    a.download = `${username}.png`;
    a.click();
  };
  img.src = qr.src;
}

interface QrModel {
  username?: string | null;
  avatar?: string | null;
  scans?: number | null;
}

const SCANS = "oi-qr-scans";
function showScans(doc: Document, box: HTMLElement, scans: number | null | undefined): void {
  doc.getElementById(SCANS)?.remove();
  if (!scans) return;
  const p = doc.createElement("p");
  p.id = SCANS;
  for (const a of box.getAttributeNames()) if (a.startsWith("data-v-")) p.setAttribute(a, "");
  p.className = "text-center";
  p.textContent = ` QR Scans: ${scans} `;
  box.before(p);
}

export function bindQr(doc: Document, model: QrModel | null, crop: (url: string) => Promise<string> = (u) => cropAvatar(doc, u)): () => void {
  const box = doc.querySelector<HTMLElement>(".b-qrcode");
  const url = doc.getElementById("add_url_to_qrcode") as HTMLInputElement | null;
  const avatar = doc.getElementById("add_avatar_to_qrcode") as HTMLInputElement | null;
  const download = [...doc.querySelectorAll<HTMLButtonElement>("button.m-profile-qrcode")][0] ?? null;
  for (const el of [url, avatar, download]) el?.setAttribute("data-oi-wired", "");
  if (download) download.disabled = true;
  if (!box) return () => {};
  showScans(doc, box, model?.scans);
  const username = model?.username ?? "";
  let avatarError = false;
  let current: (Qr & { src: string }) | null = null;
  let gen = 0;
  const measure = (text: string, size: number) => {
    const ctx = doc.createElement("canvas").getContext?.("2d");
    if (!ctx) return 0;
    ctx.font = `${size}px Roboto, sans-serif`;
    return ctx.measureText(text).width;
  };
  if (url) url.checked = getPref("url");
  if (avatar) avatar.checked = getPref("avatar");
  const canAvatar = () => !!model?.avatar && !avatarError;

  const draw = async () => {
    const mine = ++gen;
    if (!username) {
      if (url) url.disabled = true;
      if (avatar) avatar.disabled = true;
      return;
    }
    if (url) url.disabled = true;
    if (avatar) avatar.disabled = true;
    if (download) download.disabled = true;
    let face: string | null = null;
    if (avatar?.checked && canAvatar()) {
      try {
        face = await crop(model!.avatar!);
      } catch {
        avatarError = true;
        avatar.checked = false;
        setPref("avatar", false);
      }
    }
    if (mine !== gen) return;
    const qr = drawQr({ username, avatar: face, showUrl: !!url?.checked, measure });
    current = { ...qr, src: qrSrc(qr.svg) };
    let img = box.querySelector("img");
    if (!img) {
      img = doc.createElement("img");
      box.replaceChildren(img);
    }
    img.src = current.src;
    img.alt = username;
    if (url) url.disabled = false;
    if (avatar) avatar.disabled = !canAvatar();
    if (download) download.disabled = false;
  };

  const onChange = (ev: Event) => {
    const t = ev.target as HTMLInputElement | null;
    if (url && t === url) setPref("url", url.checked);
    else if (avatar && t === avatar) setPref("avatar", avatar.checked);
    else return;
    void draw();
  };
  const onClick = (ev: MouseEvent) => {
    if (!download || !(ev.target as Element | null)?.closest?.("button.m-profile-qrcode")) return;
    ev.preventDefault();
    if (current && !download.disabled) downloadQr(doc, current, username);
  };
  doc.addEventListener("change", onChange);
  doc.addEventListener("click", onClick);
  void draw();
  return () => {
    gen++;
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("click", onClick);
  };
}

export function useOfQr(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const on = page === QR_PAGE;
  const me = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && on }).data;
  const username = me?.username ?? null;
  const avatar = me?.avatar ? proxyImage(me.avatar, accountId) : null;
  const scans = useQuery({
    queryKey: ["of-qr-views", accountId],
    queryFn: () => relay.get<{ count?: number }>("/api/of/v2/users/me/profile/views/qr", { accountId }),
    enabled: !!accountId && on,
    staleTime: 5 * 60 * 1000,
    retry: false,
  }).data?.count ?? null;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindQr(doc, username ? { username, avatar, scans } : null) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, on, username, avatar, scans]);
}
