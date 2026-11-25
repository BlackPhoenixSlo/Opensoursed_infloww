"use client";


import { useCallback, useEffect, useState } from "react";

import {
  SETTINGS_EVENT,
  SETTINGS_KEY,
  readSettings,
  writeSettings,
  type RailSettings,
} from "@/lib/moneyRailStorage";

export interface RailSettingsHandle {
  settings: RailSettings | null;
  commit: (next: RailSettings) => void;
}

export function useRailSettings(): RailSettingsHandle {
  // null until localStorage is read: server and first client render can't know the pick, so null means don't decide yet.
  const [settings, setSettings] = useState<RailSettings | null>(null);

  useEffect(() => {
    const reread = () => setSettings(readSettings());
    reread();
    const onStorage = (e: StorageEvent) => {
      if (e.key === SETTINGS_KEY) reread();
    };
    window.addEventListener(SETTINGS_EVENT, reread);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(SETTINGS_EVENT, reread);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const commit = useCallback((next: RailSettings) => {
    setSettings(next);
    writeSettings(next);
  }, []);

  return { settings, commit };
}
