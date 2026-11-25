"use client";


import { useEffect, useEffectEvent } from "react";

export type Hotkey = { keys: string; run: (e: KeyboardEvent) => void };

export function matchesHotkey(keys: string, e: KeyboardEvent): boolean {
  const parts = keys.toLowerCase().split("+");
  const key = parts[parts.length - 1];
  const mods = new Set(parts.slice(0, -1));
  const mod = mods.has("mod");
  if (mod ? e.ctrlKey === e.metaKey : e.ctrlKey !== mods.has("ctrl") || e.metaKey !== mods.has("meta")) return false;
  if (e.altKey !== mods.has("alt") || e.shiftKey !== mods.has("shift")) return false;
  if (/^[a-z]$/.test(key)) {
    const typed = e.key.toLowerCase();
    return /^[a-z]$/.test(typed) ? typed === key : e.code === `Key${key.toUpperCase()}`;
  }
  return e.key.toLowerCase() === key;
}

export function useHotkeys(bindings: Hotkey[]): void {
  const onKey = useEffectEvent((e: KeyboardEvent) => {
    if (e.isComposing) return;
    const hit = bindings.find((b) => matchesHotkey(b.keys, e));
    if (!hit) return;
    e.preventDefault();
    if (!e.repeat) hit.run(e);
  });
  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKey(e);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
}
