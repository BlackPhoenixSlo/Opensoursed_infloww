"use client";


import { useEffect, useSyncExternalStore, type RefObject } from "react";
import { useTheme } from "@/hooks/useTheme";
import { persistJSON, readJSON } from "@/lib/persist";

const SWITCH = "dark_mode_switcher";

// Known flash: the generator's THEME_BOOT still follows our theme before first paint, so with sync off a dark theme shows dark until the load event.
const SYNC_KEY = "chatterly:of-display-sync:v1";
const OWN_DARK_KEY = "chatterly:of-own-dark:v1";
const SYNC_EVENT = "chatterly:of-display-sync";

export const readOfDisplaySync = (): boolean => readJSON<boolean>(SYNC_KEY) !== false;

export function writeOfDisplaySync(on: boolean): void {
  persistJSON(SYNC_KEY, on);
  try { window.dispatchEvent(new CustomEvent(SYNC_EVENT)); } catch { }
}

const readOwnDark = (): boolean => readJSON<boolean>(OWN_DARK_KEY) === true;

function writeOwnDark(on: boolean): void {
  persistJSON(OWN_DARK_KEY, on);
  try { window.dispatchEvent(new CustomEvent(SYNC_EVENT)); } catch { }
}

function subscribeSync(cb: () => void): () => void {
  const onStorage = (e: StorageEvent) => { if (e.key === SYNC_KEY || e.key === OWN_DARK_KEY) cb(); };
  window.addEventListener(SYNC_EVENT, cb);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(SYNC_EVENT, cb);
    window.removeEventListener("storage", onStorage);
  };
}

export const useOfDisplaySync = (): boolean => useSyncExternalStore(subscribeSync, readOfDisplaySync, () => true);

export function applyTheme(doc: Document, dark: boolean): void {
  doc.documentElement.classList.toggle("m-mode-dark", dark);
  const sw = doc.getElementById(SWITCH);
  if (sw?.tagName !== "INPUT") return;
  (sw as HTMLInputElement).checked = dark;
  sw.setAttribute("data-oi-wired", "");
}

export function useOfTheme(frameRef: RefObject<HTMLIFrameElement | null>, src: string): boolean {
  const { theme, setTheme } = useTheme();
  const sync = useOfDisplaySync();
  const ownDark = useSyncExternalStore(subscribeSync, readOwnDark, () => false);
  const dark = sync ? theme === "dark" : ownDark;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const onChange = (ev: Event) => {
      const t = ev.target as HTMLInputElement | null;
      if (t?.id !== SWITCH) return;
      if (sync) setTheme(t.checked ? "dark" : "light");
      else writeOwnDark(t.checked);
    };
    let bound: Document | null = null;
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      applyTheme(doc, dark);
      if (bound !== doc) {
        bound?.removeEventListener("change", onChange);
        doc.addEventListener("change", onChange);
        bound = doc;
      }
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => {
      frame.removeEventListener("load", apply);
      bound?.removeEventListener("change", onChange);
    };
  }, [frameRef, src, dark, sync, setTheme]);
  return dark;
}
