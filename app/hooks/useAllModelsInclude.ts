"use client";


import { useCallback, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "chatterly:allModelsExclude";
const LEGACY_INCLUDE_KEY = "chatterly:allModelsInclude";
const EVENT = "chatterly-all-models-include-change";

let legacyKeyCleared = false;

// Exclude-list: absence means included, so models added later still surface.
function read(): string[] {
  if (typeof window === "undefined") return [];
  if (!legacyKeyCleared) {
    legacyKeyCleared = true;
    try { window.localStorage.removeItem(LEGACY_INCLUDE_KEY); } catch { }
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string");
  } catch {
    return [];
  }
}

function write(next: string[]) {
  try {
    if (next.length === 0) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
  } catch { }
}

export interface AllModelsInclude {
  excluded: Set<string>;
  isIncluded: (id: string) => boolean;
  toggle: (id: string) => void;
  includeAll: () => void;
  excludeAll: (ids: string[]) => void;
}

export function useAllModelsInclude(): AllModelsInclude {
  const [list, setList] = useState<string[]>(() => read());

  useEffect(() => {
    const onChange = () => setList(read());
    window.addEventListener(EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);

  const excluded = useMemo(() => new Set(list), [list]);

  const isIncluded = useCallback(
    (id: string) => !excluded.has(id),
    [excluded],
  );

  const toggle = useCallback((id: string) => {
    // Fresh read(): storage is shared by every instance; captured state lets a quick second toggle clobber the first.
    const next = new Set(read());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    const arr = Array.from(next);
    setList(arr);
    write(arr);
  }, []);

  const includeAll = useCallback(() => {
    setList([]);
    write([]);
  }, []);

  const excludeAll = useCallback((ids: string[]) => {
    const next = new Set(read());
    for (const id of ids) next.add(id);
    const arr = Array.from(next);
    setList(arr);
    write(arr);
  }, []);

  return { excluded, isIncluded, toggle, includeAll, excludeAll };
}
