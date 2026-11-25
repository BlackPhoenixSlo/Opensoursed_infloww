"use client";


import { useEffect, type RefObject } from "react";

export const LANGUAGE_PAGE = "settings/display/language";
const DISPLAY_PAGE = "settings/display";
// OF keeps the language browser-side only (lang cookie, no /api2 write), so local storage here too.
const KEY = "of-mirror:lang";
const DEFAULT = "en";

export const LANGUAGES: Record<string, string> = {
  en: "English",
  zh: "ChineseSimplified",
  tw: "ChineseTraditional",
  pt: "Portuguese",
  es: "Spanish",
  ja: "Japanese",
  ko: "Korean",
  hi: "Hindi",
  fr: "French",
  de: "German",
  it: "Italian",
  ro: "Romanian",
  ar: "Arabic",
  uk: "Ukrainian",
  ru: "Russian",
};

export function currentLanguage(): string {
  try {
    const code = localStorage.getItem(KEY);
    return code && code in LANGUAGES ? code : DEFAULT;
  } catch {
    return DEFAULT;
  }
}
function saveLanguage(code: string) {
  try {
    localStorage.setItem(KEY, code);
  } catch {
  }
}

const radios = (doc: Document) => [...doc.querySelectorAll<HTMLInputElement>("input[type=radio][id^='lang-']")];
const check = (doc: Document, code: string) => radios(doc).forEach((r) => (r.checked = r.value === code));

export function bindLanguage(doc: Document, page: string): () => void {
  if (page === DISPLAY_PAGE) {
    const sub = doc.querySelector("a[href$='/settings/display/language'] .b-menu-list__subtext");
    if (sub) sub.textContent = LANGUAGES[currentLanguage()];
    return () => {};
  }
  if (page !== LANGUAGE_PAGE) return () => {};
  radios(doc).forEach((r) => r.setAttribute("data-oi-wired", ""));
  check(doc, currentLanguage());
  const onChange = (ev: Event) => {
    const t = ev.target as HTMLInputElement | null;
    if (!t || t.type !== "radio" || !t.id.startsWith("lang-") || !(t.value in LANGUAGES)) return;
    saveLanguage(t.value);
    // OF's radios have one name each: only the model value makes them exclusive.
    check(doc, t.value);
  };
  doc.addEventListener("change", onChange);
  return () => doc.removeEventListener("change", onChange);
}

export function useOfLanguage(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const on = page === LANGUAGE_PAGE || page === DISPLAY_PAGE;
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindLanguage(doc, page) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, on, page]);
}
