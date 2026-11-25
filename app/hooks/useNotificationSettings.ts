"use client";


import { useCallback, useEffect, useState } from "react";

import {
  readNotifSettings,
  writeNotifSettings,
  type NotifSettings,
  type NotifTypeKey,
} from "@/lib/notifSettings";

export function useNotificationSettings() {
  const [settings, setSettings] = useState<NotifSettings>(() => readNotifSettings());

  useEffect(() => {
    function refresh() { setSettings(readNotifSettings()); }
    function onStorage(e: StorageEvent) {
      if (e.key === "chatterly:notif-settings:v1") refresh();
    }
    window.addEventListener("chatterly:notif-settings", refresh);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("chatterly:notif-settings", refresh);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const update = useCallback((patch: Partial<NotifSettings>) => {
    // Side effects stay out of setSettings' updater: React runs updaters during render and the event setState'd a sibling.
    const next = { ...settings, ...patch };
    setSettings(next);
    writeNotifSettings(next);
  }, [settings]);

  const setToast = useCallback((key: NotifTypeKey, on: boolean) => {
    const next = { ...settings, toast: { ...settings.toast, [key]: on } };
    setSettings(next);
    writeNotifSettings(next);
  }, [settings]);

  const setBubble = useCallback((key: NotifTypeKey, on: boolean) => {
    const next = { ...settings, bubble: { ...settings.bubble, [key]: on } };
    setSettings(next);
    writeNotifSettings(next);
  }, [settings]);

  return { settings, update, setToast, setBubble };
}
